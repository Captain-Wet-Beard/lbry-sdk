import os
import asyncio
import logging
import signal
from typing import List, Optional, Tuple, NamedTuple

from aiohttp.web import GracefulExit

from lbry.db import Database
from lbry.db.constants import TXO_TYPES
from lbry.schema.result import Censor
from lbry.blockchain.transaction import Transaction, Output
from lbry.blockchain.ledger import Ledger
from lbry.wallet import WalletManager
from lbry.event import EventController

log = logging.getLogger(__name__)


class BlockEvent(NamedTuple):
    height: int


class Sync:

    def __init__(self, service: 'Service'):
        self.service = service

        self._on_block_controller = EventController()
        self.on_block = self._on_block_controller.stream

        self._on_progress_controller = EventController()
        self.on_progress = self._on_progress_controller.stream

        self._on_ready_controller = EventController()
        self.on_ready = self._on_ready_controller.stream

    def on_bulk_started(self):
        return self.on_progress.where()  # filter for bulk started event

    def on_bulk_started(self):
        return self.on_progress.where()  # filter for bulk started event

    def on_bulk_finished(self):
        return self.on_progress.where()  # filter for bulk finished event

    async def start(self):
        raise NotImplementedError

    async def stop(self):
        raise NotImplementedError


class Service:
    """
    Base class for light client and full node LBRY service implementations.
    """

    sync: Sync

    def __init__(self, ledger: Ledger, db_url: str):
        self.ledger, self.conf = ledger, ledger.conf
        self.db = Database(ledger, db_url)
        self.wallets = WalletManager(ledger, self.db)

        #self.on_address = sync.on_address
        #self.accounts = sync.accounts
        #self.on_header = sync.on_header
        #self.on_ready = sync.on_ready
        #self.on_transaction = sync.on_transaction

        # sync has established connection with a source from which it can synchronize
        # for full service this is lbrycrd (or sync service) and for light this is full node
        self._on_connected_controller = EventController()
        self.on_connected = self._on_connected_controller.stream

    def run(self):
        loop = asyncio.get_event_loop()

        def exit():
            raise GracefulExit()

        try:
            loop.add_signal_handler(signal.SIGINT, exit)
            loop.add_signal_handler(signal.SIGTERM, exit)
        except NotImplementedError:
            pass  # Not implemented on Windows

        try:
            loop.run_until_complete(self.start())
            loop.run_forever()
        except (GracefulExit, KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            loop.run_until_complete(self.stop())
            logging.shutdown()

        if hasattr(loop, 'shutdown_asyncgens'):
            loop.run_until_complete(loop.shutdown_asyncgens())

    async def start(self):
        await self.db.open()
        await self.wallets.ensure_path_exists()
        await self.wallets.load()
        await self.sync.start()

    async def stop(self):
        await self.sync.stop()
        await self.db.close()

    def get_status(self):
        pass

    def get_version(self):
        pass

    async def find_ffmpeg(self):
        pass

    async def get(self, uri, **kwargs):
        pass

    async def get_block_address_filters(self):
        raise NotImplementedError

    async def get_transaction_address_filters(self, block_hash):
        raise NotImplementedError

    def create_wallet(self, file_name):
        path = os.path.join(self.conf.wallet_dir, file_name)
        return self.wallet_manager.import_wallet(path)

    async def get_addresses(self, **constraints):
        return await self.db.get_addresses(**constraints)

    def reserve_outputs(self, txos):
        return self.db.reserve_outputs(txos)

    def release_outputs(self, txos):
        return self.db.release_outputs(txos)

    def release_tx(self, tx):
        return self.release_outputs([txi.txo_ref.txo for txi in tx.inputs])

    def get_utxos(self, **constraints):
        self.constraint_spending_utxos(constraints)
        return self.db.get_utxos(**constraints)

    async def get_txos(self, resolve=False, **constraints) -> Tuple[List[Output], Optional[int]]:
        txos, count = await self.db.get_txos(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), txos), count
        return txos, count

    def get_txo_sum(self, **constraints):
        return self.db.get_txo_sum(**constraints)

    def get_txo_plot(self, **constraints):
        return self.db.get_txo_plot(**constraints)

    def get_transactions(self, **constraints):
        return self.db.get_transactions(**constraints)

    async def get_transaction(self, tx_hash: bytes):
        tx = await self.db.get_transaction(tx_hash=tx_hash)
        if tx:
            return tx
        try:
            raw, merkle = await self.ledger.network.get_transaction_and_merkle(tx_hash)
        except CodeMessageError as e:
            if 'No such mempool or blockchain transaction.' in e.message:
                return {'success': False, 'code': 404, 'message': 'transaction not found'}
            return {'success': False, 'code': e.code, 'message': e.message}
        height = merkle.get('block_height')
        tx = Transaction(unhexlify(raw), height=height)
        if height and height > 0:
            await self.ledger.maybe_verify_transaction(tx, height, merkle)
        return tx

    async def search_transactions(self, txids):
        raise NotImplementedError

    async def announce_addresses(self, address_manager, addresses: List[str]):
        await self.ledger.announce_addresses(address_manager, addresses)

    async def get_address_manager_for_address(self, address):
        details = await self.db.get_address(address=address)
        for account in self.accounts:
            if account.id == details['account']:
                return account.address_managers[details['chain']]
        return None

    async def reset(self):
        self.ledger.config = {
            'auto_connect': True,
            'default_servers': self.config.lbryum_servers,
            'data_path': self.config.wallet_dir,
        }
        await self.ledger.stop()
        await self.ledger.start()

    async def get_best_blockhash(self):
        if len(self.ledger.headers) <= 0:
            return self.ledger.genesis_hash
        return (await self.ledger.headers.hash(self.ledger.headers.height)).decode()

    async def maybe_broadcast_or_release(self, tx, blocking=False, preview=False):
        if preview:
            return await self.release_tx(tx)
        try:
            await self.broadcast(tx)
            if blocking:
                await self.wait(tx, timeout=None)
        except Exception:
            await self.release_tx(tx)
            raise

    async def broadcast(self, tx):
        raise NotImplementedError

    async def wait(self, tx: Transaction, height=-1, timeout=1):
        raise NotImplementedError

    async def resolve(self, accounts, urls, **kwargs):
        raise NotImplementedError

    async def search_claims(self, accounts, **kwargs) -> Tuple[List[Output], Optional[int], Censor]:
        raise NotImplementedError

    async def get_claim_by_claim_id(self, accounts, claim_id, **kwargs) -> Output:
        for claim in (await self.search_claims(accounts, claim_id=claim_id, **kwargs))[0]:
            return claim

    @staticmethod
    def constraint_spending_utxos(constraints):
        constraints['txo_type__in'] = (0, TXO_TYPES['purchase'])

    async def get_purchases(self, wallet, resolve=False, **constraints):
        purchases = await wallet.get_purchases(**constraints)
        if resolve:
            claim_ids = [p.purchased_claim_id for p in purchases]
            try:
                resolved, _, _, _ = await self.claim_search([], claim_ids=claim_ids)
            except Exception as err:
                if isinstance(err, asyncio.CancelledError):  # TODO: remove when updated to 3.8
                    raise
                log.exception("Resolve failed while looking up purchased claim ids:")
                resolved = []
            lookup = {claim.claim_id: claim for claim in resolved}
            for purchase in purchases:
                purchase.purchased_claim = lookup.get(purchase.purchased_claim_id)
        return purchases

    async def _resolve_for_local_results(self, accounts, txos):
        results = []
        response = await self.resolve(
            accounts, [txo.permanent_url for txo in txos if txo.can_decode_claim]
        )
        for txo in txos:
            resolved = response.get(txo.permanent_url) if txo.can_decode_claim else None
            if isinstance(resolved, Output):
                resolved.update_annotations(txo)
                results.append(resolved)
            else:
                if isinstance(resolved, dict) and 'error' in resolved:
                    txo.meta['error'] = resolved['error']
                results.append(txo)
        return results

    async def resolve_collection(self, collection, offset=0, page_size=1):
        claim_ids = collection.claim.collection.claims.ids[offset:page_size+offset]
        try:
            resolve_results, _, _, _ = await self.claim_search([], claim_ids=claim_ids)
        except Exception as err:
            if isinstance(err, asyncio.CancelledError):  # TODO: remove when updated to 3.8
                raise
            log.exception("Resolve failed while looking up collection claim ids:")
            return []
        claims = []
        for claim_id in claim_ids:
            found = False
            for txo in resolve_results:
                if txo.claim_id == claim_id:
                    claims.append(txo)
                    found = True
                    break
            if not found:
                claims.append(None)
        return claims