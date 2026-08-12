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
    # groups/contacts fields work as before: names + phones resolved via the API.
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


class CountingClient:
    def __init__(self, groups, chats, contacts):
        self._g, self._c, self._ct = groups, chats, contacts
        self.calls = 0
    async def get_groups(self): self.calls += 1; return self._g
    async def get_chats(self): self.calls += 1; return self._c
    async def get_contacts(self): self.calls += 1; return self._ct


@pytest.mark.asyncio
async def test_resolve_cached_avoids_refetch_on_restart(tmp_path):
    cache = tmp_path / "allowlist.json"
    targets = Targets(groups=["Project Team"], contacts=["+919999999991"])
    data = dict(
        groups=[{"id": "g1@g.us", "name": "Project Team"}],
        chats=[{"id": "g1@g.us", "type": "group", "name": "Project Team"}],
        contacts=[{"id": "91@s.whatsapp.net", "phone": "+919999999991", "name": "Mom"}],
    )
    c1 = CountingClient(**data)
    allow1 = await Resolver(c1).resolve_cached(targets, cache_path=str(cache))
    assert "g1@g.us" in allow1
    assert c1.calls == 3
    assert cache.exists()

    c2 = CountingClient(**data)
    r2 = Resolver(c2)
    allow2 = await r2.resolve_cached(targets, cache_path=str(cache))
    assert c2.calls == 0
    assert r2.cache_hit is True
    assert allow2 == allow1


@pytest.mark.asyncio
async def test_resolve_cached_invalidates_when_targets_change(tmp_path):
    cache = tmp_path / "allowlist.json"
    data = dict(
        groups=[{"id": "g1@g.us", "name": "Project Team"}, {"id": "g2@g.us", "name": "Other"}],
        chats=[], contacts=[],
    )
    await Resolver(CountingClient(**data)).resolve_cached(
        Targets(groups=["Project Team"]), cache_path=str(cache))
    c2 = CountingClient(**data)
    r2 = Resolver(c2)
    allow2 = await r2.resolve_cached(Targets(groups=["Other"]), cache_path=str(cache))
    assert c2.calls == 3
    assert r2.cache_hit is False
    assert "g2@g.us" in allow2


class ExplodingClient:
    async def get_groups(self): raise AssertionError("API should not be called")
    async def get_chats(self): raise AssertionError("API should not be called")
    async def get_contacts(self): raise AssertionError("API should not be called")


@pytest.mark.asyncio
async def test_ids_field_skips_api_entirely():
    # The `ids` field is used directly -> zero API calls.
    r = Resolver(ExplodingClient())
    allow = await r.resolve(Targets(ids=[
        "120363abc@g.us",
        "919984351847@s.whatsapp.net",
        "120363zzz@newsletter",
    ]))
    assert set(allow) == {"120363abc@g.us", "120363zzz@newsletter",
                          "919984351847", "919984351847@s.whatsapp.net"}
    assert allow["120363abc@g.us"]["type"] == "group"
    assert allow["919984351847@s.whatsapp.net"]["type"] == "contact"
    assert allow["919984351847"]["type"] == "contact"
    assert allow["120363zzz@newsletter"]["type"] == "channel"
    assert r.unresolved == []


@pytest.mark.asyncio
async def test_mixed_ids_field_and_named_groups():
    # ids used directly + a named group resolved via API.
    client = CountingClient(
        groups=[{"id": "g_name@g.us", "name": "By Name"}],
        chats=[{"id": "g_name@g.us", "type": "group", "name": "By Name"}],
        contacts=[],
    )
    r = Resolver(client)
    allow = await r.resolve(Targets(groups=["By Name"], ids=["g_id@g.us"]))
    assert "g_id@g.us" in allow and allow["g_id@g.us"]["type"] == "group"
    assert "g_name@g.us" in allow
    assert client.calls == 3  # API was needed for the named group


@pytest.mark.asyncio
async def test_ids_field_cached_zero_calls_on_first_run(tmp_path):
    cache = tmp_path / "allowlist.json"
    targets = Targets(ids=["120363abc@g.us"])
    c = CountingClient(groups=[], chats=[], contacts=[])
    allow = await Resolver(c).resolve_cached(targets, cache_path=str(cache))
    assert "120363abc@g.us" in allow
    assert c.calls == 0  # no API even on first run


@pytest.mark.asyncio
async def test_ids_field_contact_both_forms():
    # bare digits (as whapi /contacts returns) and full JID both match
    r = Resolver(ExplodingClient())
    allow = await r.resolve(Targets(ids=["919468930964", "918799507812@s.whatsapp.net"]))
    assert allow["919468930964"]["type"] == "contact"
    assert "919468930964@s.whatsapp.net" in allow
    assert allow["918799507812@s.whatsapp.net"]["type"] == "contact"
    assert "918799507812" in allow
    assert r.unresolved == []
