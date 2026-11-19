import tempfile
import unittest
from pathlib import Path

from telethon.tl.types import PeerChannel, PeerChat

from app import db, inviting


class FakeClient:
    """Кэш сессии: находит только сущности из ``known``."""

    def __init__(self, known=(), after_dialogs=()):
        self.known = list(known)
        self.after_dialogs = list(after_dialogs)
        self.requests = []
        self.dialogs_loaded = False

    async def get_entity(self, ref):
        self.requests.append(ref)
        if ref in self.known:
            return ("entity", ref)
        raise ValueError("Could not find the input entity for %r" % (ref,))

    async def iter_dialogs(self):
        self.dialogs_loaded = True
        self.known.extend(self.after_dialogs)
        if False:
            yield None


class ResolveTargetChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db.connect()

    def tearDown(self):
        if db._conn is not None:
            db._conn.close()
        db._conn = None
        self.tmp.cleanup()

    def _chat(self, chat_id, kind, username=None):
        db.ex(
            "INSERT INTO chats (id,title,username,kind) VALUES (?,?,?,?)",
            (chat_id, "chat", username, kind),
        )

    async def test_supergroup_id_is_opened_as_channel_not_user(self):
        self._chat(4478431095, "supergroup", "p2pwide")
        client = FakeClient(known=[PeerChannel(4478431095)])
        entity = await inviting.resolve_target_chat(client, 4478431095)
        self.assertEqual(entity, ("entity", PeerChannel(4478431095)))
        self.assertNotIn(4478431095, client.requests)

    async def test_basic_group_is_opened_as_chat(self):
        self._chat(555, "group")
        client = FakeClient(known=[PeerChat(555)])
        entity = await inviting.resolve_target_chat(client, 555)
        self.assertEqual(entity, ("entity", PeerChat(555)))

    async def test_cache_miss_falls_back_to_username(self):
        self._chat(4478431095, "supergroup", "p2pwide")
        client = FakeClient(known=["p2pwide"])
        entity = await inviting.resolve_target_chat(client, 4478431095)
        self.assertEqual(entity, ("entity", "p2pwide"))
        self.assertFalse(client.dialogs_loaded)

    async def test_private_chat_loads_dialogs_and_retries(self):
        self._chat(777, "supergroup")
        client = FakeClient(after_dialogs=[PeerChannel(777)])
        entity = await inviting.resolve_target_chat(client, 777)
        self.assertEqual(entity, ("entity", PeerChannel(777)))
        self.assertTrue(client.dialogs_loaded)

    async def test_unknown_chat_raises_non_value_error(self):
        client = FakeClient()
        with self.assertRaises(RuntimeError):
            await inviting.resolve_target_chat(client, 999)


if __name__ == "__main__":
    unittest.main()
