from unittest import TestCase
from binascii import hexlify

from lbry.wallet import words
from lbry.wallet.mnemonic import (
    get_languages, is_phrase_valid as is_valid,
    sync_generate_phrase as generate,
    sync_derive_key_from_phrase as derive
)


class TestMnemonic(TestCase):

    def test_get_languages(self):
        languages = get_languages()
        self.assertEqual(len(languages), 6)
        for lang in languages:
            self.assertEqual(len(getattr(words, lang)), 2048)

    def test_is_phrase_valid(self):
        self.assertFalse(is_valid('en', ''))
        self.assertFalse(is_valid('en', 'foo'))
        self.assertFalse(is_valid('en', 'awesomeball'))
        self.assertTrue(is_valid('en', 'awesome ball'))

        # check normalize works (these are not the same)
        self.assertTrue(is_valid('ja', 'るいじ りんご'))
        self.assertTrue(is_valid('ja', 'るいじ りんご'))

    def test_generate_phrase(self):
        self.assertGreaterEqual(len(generate('en').split()), 11)
        self.assertGreaterEqual(len(generate('ja').split()), 11)

    def test_phrase_to_key(self):
        self.assertEqual(
            hexlify(derive(
                "carbon smart garage balance margin twelve che"
                "st sword toast envelope bottom stomach absent"
            )),
            b'919455c9f65198c3b0f8a2a656f13bd0ecc436abfabcb6a2a1f063affbccb628'
            b'230200066117a30b1aa3aec2800ddbd3bf405f088dd7c98ba4f25f58d47e1baf'
        )