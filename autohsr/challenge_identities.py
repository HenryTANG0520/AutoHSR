"""Finite confirmed outfit identities, used only for challenge deduplication.

Asset IDs remain exact in plans. Unknown relations are deliberately absent:
neither narrative identity, shared name prefixes nor path labels prove that
two independently catalogued playable characters are mutually exclusive.

The pinned M7 support manifest maps these exact IDs to outfit names.
The publisher's CMS sources below were read in full on 2026-11-05. Hashes
bind their UTF-8 sContent fields. The separate official 4.4 announcement
for Sparxie is linked in the high-difficulty documentation.
"""
from types import MappingProxyType


CMS_BASE='https://sg-public-api-static.hoyoverse.com/content_v2_user/app/113fe6d3b4514cdd/getContent'
SOURCES=(
    ('https://hsr.hoyoverse.com/en-us/news/127987?type=activity',127987,
     '4b57b220ac41f2a82ed547e48680a2f2d7af95e313b7c4a33359f41fc1021e2d',
     'Nascent Spring is an outfit for March 7th (Preservation: Ice).'),
    ('https://hsr.hoyoverse.com/en-us/news/157441',157441,
     '33cd38b6022c3b700afb88d3a8800d7d6c961a1d03e846e41186cbf4a0db5324',
     'Spring Missive is an outfit for Firefly (Destruction: Fire).'),
    ('https://hsr.hoyoverse.com/en-us/news/163625',163625,
     '8dd4194239d825a6b8e12f2ff521a538a109aff6f5bfdbb0a853d8f6da9967c8',
     'Gossamer Flutter is an outfit for Castorice (Remembrance: Quantum).'),
    ('https://hsr.hoyoverse.com/en-us/news/166468',166468,
     '807030045374b263e96783b441ea0dfd846a3451239675de59c4316299d9c288',
     'Warm Cotton Skies belongs to Hyacine; Lunar Blossoming belongs to Evanescia.'),
)

# Explicit equality groups only. No prefix matching or synthesized IDs.
CONFIRMED_GROUPS=(
    ('March7th','March7thNascentSpring'),
    ('Firefly','FireflySpringMissive'),
    ('Castorice','CastoriceGossamerFlutter'),
    ('Hyacine','HyacineWarmCottonSkies'),
    ('Evanescia','EvanesciaLunarBlossoming'),
    # The publisher's version 4.4 announcement (165197) confirms Candy-Coated Waves.
    ('Sparxie','SparxieCandyCoatedWaves'),
)
_UNIT_KEYS=MappingProxyType({asset:group[0] for group in CONFIRMED_GROUPS for asset in group})


def unit_key(asset_id):
    """Compare confirmed ownership only; this does not validate an asset ID."""
    if type(asset_id) is not str:
        raise ValueError('单位去重需要明确角色标识。')
    return _UNIT_KEYS.get(asset_id,asset_id)
