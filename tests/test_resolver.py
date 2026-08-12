import pytest
from app.config import Targets
from app.resolver import Resolver

class FakeClient:
    def __init__(self, groups, chats, contacts):
        self._g, self._c, self._ct = groups, chats, contacts
    async def get_groups(self): return self._g
    async def get_chats(self): return self._c
    async def get_contacts(self): return self._ct

@pytest.mark.asyncio
async def test_resolve_group_by_name_and_contact_by_phone():
    client = FakeClient(
        groups=[{"id": "g1@g.us", "name": "Project Team"}],
        chats=[{"id": "g1@g.us", "type": "group", "name": "Project Team"},
               {"id": "91@s.whatsapp.net", "type": "contact", "name": "Mom"}],
        contacts=[{"id": "91@s.whatsapp.net", "phone": "+919999999991", "name": "Mom"}],
    )
    r = Resolver(client)
    allow = await r.resolve(Targets(groups=["Project Team"], contacts=["+919999999991"]))
    assert "g1@g.us" in allow
    assert allow["g1@g.us"]["type"] == "group"
    assert "91@s.whatsapp.net" in allow
    assert allow["91@s.whatsapp.net"]["type"] == "contact"
    assert r.unresolved == []

@pytest.mark.asyncio
async def test_unresolved_name_recorded():
    client = FakeClient(groups=[], chats=[], contacts=[])
    r = Resolver(client)
    allow = await r.resolve(Targets(groups=["Nope"]))
    assert allow == {}
    assert "Nope" in r.unresolved
