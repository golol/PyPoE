"""
Wiki gems exporter

Overview
===============================================================================

+----------+------------------------------------------------------------------+
| Path     | PyPoE/cli/exporter/wiki/parsers/gems.py                          |
+----------+------------------------------------------------------------------+
| Version  | 1.0.0a0                                                          |
+----------+------------------------------------------------------------------+
| Revision | $Id$                  |
+----------+------------------------------------------------------------------+
| Author   | Omega_K2                                                         |
+----------+------------------------------------------------------------------+

Description
===============================================================================

http://pathofexile.gamepedia.com

Agreement
===============================================================================

See PyPoE/LICENSE
"""

# =============================================================================
# Imports
# =============================================================================

# Python
import re
import warnings
import os
from collections import defaultdict, OrderedDict

# Self
from PyPoE.poe.constants import RARITY
from PyPoE.poe.file.ot import OTFile
from PyPoE.poe.sim.formula import gem_stat_requirement, GemTypes
from PyPoE.cli.core import console, Msg
from PyPoE.cli.exporter.wiki.handler import ExporterHandler, ExporterResult
from PyPoE.cli.exporter.wiki import parser
from PyPoE.cli.exporter.wiki.parsers.skill import SkillParserShared

# =============================================================================
# Functions
# =============================================================================


def _apply_column_map(infobox, column_map, list_object):
    for k, data in column_map:
        value = list_object[k]
        if data.get('condition') and not data['condition'](value):
            continue

        if data.get('format'):
            value = data['format'](value)
        infobox[data['template']] = value


def _type_factory(data_file, data_mapping, row_index=True, function=None,
                  fail_condition=False):
    def func(self, infobox, base_item_type):
        try:
            data = self.rr[data_file].index['BaseItemTypesKey'][
                base_item_type.rowid if row_index else base_item_type['Id']
            ]
        except KeyError:
            warnings.warn(
                'Missing %s info for "%s"' % (data_file, base_item_type['Name'])
            )
            return fail_condition

        _apply_column_map(infobox, data_mapping, data)

        if function:
            function(self, infobox, base_item_type, data)

        return True
    return func


def _simple_conflict_factory(data):
    def _conflict_handler(self, infobox, base_item_type):
        appendix = data.get(base_item_type['Id'])
        if appendix is None:
            return base_item_type['Name']
        else:
            return base_item_type['Name'] + appendix

    return _conflict_handler

# =============================================================================
# Classes
# =============================================================================


class WikiCondition(parser.WikiCondition):
    COPY_KEYS = (
        # for skills
        'radius',
        'radius_description',
        'radius_secondary',
        'radius_secondary_description',
        'radius_tertiary',
        'radius_tertiary_description',
        'has_percentage_mana_cost',
        'has_reservation_mana_cost',
        #
        # all items
        #
        'name_list',
        'quality',

        # Icons
        'inventory_icon',
        'alternate_art_inventory_icons',

        # Drop restrictions
        'drop_enabled',
        'drop_leagues',
        'drop_areas',
        'drop_text',

        # Item flags
        'is_corrupted',
        'is_relic',
        'can_not_be_traded_or_modified',
        'suppress_improper_modifiers_category',

        # Version information
        'release_version',
        'removal_version',

        # prophecies
        'prophecy_objective',
        'prophecy_reward',
    )
    COPY_MATCH = re.compile(
        r'^(upgraded_from_set|implicit[0-9]+_text).*'
        , re.UNICODE)

    NAME = 'Item'
    INDENT = 36
    ADD_INCLUDE = False


class ItemsHandler(ExporterHandler):
    def __init__(self, sub_parser, *args, **kwargs):
        super(ItemsHandler, self).__init__(self, sub_parser, *args, **kwargs)
        self.parser = sub_parser.add_parser('items', help='Items Exporter')
        self.parser.set_defaults(func=lambda args: self.parser.print_help())
        sub = self.parser.add_subparsers()

        #
        # Generic base item export
        #
        parser = sub.add_parser(
            'by_name',
            help='Extracts the item information based on item names'
        )
        self.add_default_parsers(
            parser=parser,
            cls=ItemsParser,
            func=ItemsParser.by_name,
        )
        self._shared_item_arguments(parser)

        parser.add_argument(
            '-mid', '--is-metadata-id',
            help='Whether the given item names are metadata ids instead',
            action='store_true',
            dest='is_metadata_id',
        )

        parser.add_argument(
            'item',
            help='Name of the item; can be specified multiple times',
            nargs='+',
        )

        parser = sub.add_parser(
            'by_filter',
            help='Extracts all items matching various filters',
        )

        self.add_default_parsers(
            parser=parser,
            cls=ItemsParser,
            func=ItemsParser.by_filter,
        )
        self._shared_item_arguments(parser)

        parser.add_argument(
            '-ft-n', '--filter-name',
            help='Filter by item name using regular expression.',
            dest='re_name',
        )

        parser.add_argument(
            '-ft-id', '--filter-id', '--filter-metadata-id',
            help='Filter by item metadata id using regular expression',
            dest='re_id',
        )

        #
        # Prophecies
        #
        parser = sub.add_parser(
            'prophecy',
            help='Extracts the prophecy information'
        )
        self.add_default_parsers(
            parser=parser,
            cls=ItemsParser,
            func=ItemsParser.prophecy,
        )

        parser.add_argument(
            '--allow-disabled',
            help='Allows disabled prophecies to be exported',
            action='store_true',
            dest='allow_disabled',
            default=False,
        )

        parser.add_argument(
            'name',
            help='Name of the prophecy; can be specified multiple times',
            nargs='+',
        )

    def add_default_parsers(self, *args, **kwargs):
        super().add_default_parsers(*args, **kwargs)
        self.add_format_argument(kwargs['parser'])

    def _shared_item_arguments(self, parser):
        parser.add_argument(
            '-ft-c', '--filter-class',
            help='Filter by item class(es). Case sensitive.',
            nargs='*',
            dest='item_class',
        )

        self.add_image_arguments(parser)


class ItemsParser(SkillParserShared):
    _regex_format = re.compile(
        '(?P<index>x|y|z)'
        '(?:[\W]*)'
        '(?P<tag>%|second)',
        re.IGNORECASE
    )

    # Core files we need to load
    _files = [
        'BaseItemTypes.dat',
    ]

    # Core translations we need
    _translations = [
        'stat_descriptions.txt',
        'gem_stat_descriptions.txt',
        'skill_stat_descriptions.txt',
        'active_skill_gem_stat_descriptions.txt',
    ]

    _IGNORE_DROP_LEVEL_CLASSES = (
        'Hideout Doodads',
        'Microtransactions',
        'Labyrinth Item',
        'Labyrinth Trinket',
        'Labyrinth Map Item',
    )

    _IGNORE_DROP_LEVEL_ITEMS = {
        'Alchemy Shard',
        'Alteration Shard',
        'Enchant',
        'Imprint',
        'Transmutation Shard',
        'Scroll Fragment',
    }

    _DROP_DISABLED_ITEMS = {
        'Eternal Orb',
    }

    _DROP_DISABLED_ITEMS_BY_ID = {
        'Metadata/Items/Quivers/QuiverDescent',
    }

    # Unreleased or disabled items to avoid exporting to the wiki
    _SKIP_ITEMS_BY_ID = {
        'Metadata/Items/Gems/SkillGemLightningTendrilsChannelled',

        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionSpectralThrowEbony',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionFirstBlood',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionFirstBloodWeaponEffect',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionTitanPlate',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionStatueSummonSkeletons2',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionStatueSummonSkeletons3',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionStatueSummonSkeletons4',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionAlternatePortal',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionBloodSlam',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionNewRaiseSpectre',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionNewRaiseZombie',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionNewTotem',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionPlinthWarp',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionWhiteWeapon',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionYellowWeapon',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionHeartWeapon2015',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionPortalSteam1',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionTestCharacterPortrait',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionTestCharacterPortrait2',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionAuraEffect1',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionAuraEffect2',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionAuraEffect3',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionAuraEffect4',
        'Metadata/Items/MicrotransactionSkillEffects/MicrotransactionBloodRavenSummonRagingSpirit',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionMarkOfThePhoenixPurple',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionWuqiWeaponEffect',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionBlackguardCape',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionGhostflameCharacterEffect',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionDemonhandClaw',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionDivineShield',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionEldritchWings',

        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencent1Frame',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencent2Frame',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencent3Frame',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencent4Frame',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencent5Frame',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencent6Frame',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencent7Frame',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge1_1',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge1_2',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge1_3',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge1_4',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge1_5',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge1_6',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge1_7',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge2_1',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge2_2',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge2_3',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge2_4',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge2_5',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge2_6',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge2_7',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge3_1',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge3_2',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge3_3',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge3_4',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge3_5',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge3_6',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge3_7',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge4_1',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge4_2',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge4_3',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge4_4',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge4_5',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge4_6',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge4_7',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge5_1',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge5_2',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge5_3',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge5_4',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge5_5',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge5_6',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge5_7',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge6_1',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge6_2',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge6_3',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge6_4',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge6_5',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge6_6',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge6_7',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge7_1',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge7_2',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge7_3',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge7_4',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge7_5',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge7_6',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge7_7',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge8_1',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge8_2',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge8_3',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge8_4',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge8_5',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge8_6',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge8_7',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge9_1',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge9_2',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge9_3',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge9_4',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge9_5',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge9_6',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge9_7',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge10_1',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge10_2',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge10_3',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge10_4',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge10_5',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge10_6',
        'Metadata/Items/MicrotransactionCharacterEffects/MicrotransactionTencentBadge10_7',
    }

    _attribute_map = OrderedDict((
        ('Str', 'Strength'),
        ('Dex', 'Dexterity'),
        ('Int', 'Intelligence'),
    ))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._parsed_args = None

    def _skill_gem(self, infobox, base_item_type):
        try:
            skill_gem = self.rr['SkillGems.dat'].index['BaseItemTypesKey'][
                base_item_type.rowid]
        except KeyError:
            return False

        # SkillGems.dat
        for attr_short, attr_long in self._attribute_map.items():
            if not skill_gem[attr_short]:
                continue
            infobox[attr_long.lower() + '_percent'] = skill_gem[attr_short]

        infobox['gem_tags'] = ', '.join(
            [gt['Tag'] for gt in skill_gem['GemTagsKeys'] if gt['Tag']]
        )

        # No longer used
        #

        # TODO: Maybe catch empty stuff here?
        exp = 0
        exp_level = []
        exp_total = []
        for row in self.rr['ItemExperiencePerLevel.dat']:
            if row['BaseItemTypesKey'] == base_item_type:
                exp_new = row['Experience']
                exp_level.append(exp_new - exp)
                exp_total.append(exp_new)
                exp = exp_new

        if not exp_level:
            console('No experience progression found for "%s" - assuming max '
                    'level 1' %
                    base_item_type['Name'], msg=Msg.error)
            exp_total = [0]

        max_level = len(exp_total)-1
        ge = skill_gem['GrantedEffectsKey']

        self._skill(ge=ge, infobox=infobox, parsed_args=self._parsed_args,
                    msg_name=base_item_type['Name'], max_level=max_level)

        # some descriptions come from active skills which are parsed in above
        # function
        if 'gem_description' not in infobox:
            infobox['gem_description'] = skill_gem['Description']

        #
        # Output handling for progression
        #

        # Body
        map2 = {
            'Str': 'strength_requirement',
            'Int': 'intelligence_requirement',
            'Dex': 'dexterity_requirement',
        }

        if base_item_type['ItemClassesKey']['Name'] == 'Active Skill Gems':
            gtype = GemTypes.active
        elif base_item_type['ItemClassesKey']['Name'] == 'Support Skill Gems':
            gtype = GemTypes.support

        # +1 for gem levels starting at 1
        # +1 for being able to corrupt gems to +1 level
        # +1 for python counting only up to, but not including the number
        for i in range(1, max_level+3):
            prefix = 'level%s_' % i
            for attr in ('Str', 'Dex', 'Int'):
                if skill_gem[attr]:
                    try:
                        infobox[prefix + map2[attr]] = gem_stat_requirement(
                            level=infobox[prefix + 'level_requirement'],
                            gtype=gtype,
                            multi=skill_gem[attr],
                        )
                    except ValueError as e:
                        warnings.warn(str(e))
            try:
                # Index starts at 0 while levels start at 1
                infobox[prefix + 'experience'] = exp_total[i-1]
            except IndexError:
                pass

        return True

    def _type_level(self, infobox, base_item_type):
        infobox['required_level'] = base_item_type['DropLevel']

        return True

    _type_attribute = _type_factory(
        data_file='ComponentAttributeRequirements.dat',
        data_mapping=(
            ('ReqStr', {
                'template': 'required_strength',
                'condition': lambda v: v > 0,
            }),
            ('ReqDex', {
                'template': 'required_dexterity',
                'condition': lambda v: v > 0,
            }),
            ('ReqInt', {
                'template': 'required_intelligence',
                'condition': lambda v: v > 0,
            }),
        ),
        row_index=False,
    )

    def _type_amulet(self, infobox, base_item_type):
        match = re.search('Talisman([0-9])', base_item_type['Id'])
        if match:
            infobox['is_talisman'] = True
            infobox['talisman_tier'] = match.group(1)

        return True

    _type_armour = _type_factory(
        data_file='ComponentArmour.dat',
        data_mapping=(
            ('Armour', {
                'template': 'armour',
                'condition': lambda v: v > 0,
            }),
            ('Evasion', {
                'template': 'evasion',
                'condition': lambda v: v > 0,
            }),
            ('EnergyShield', {
                'template': 'energy_shield',
                'condition': lambda v: v > 0,
            }),
        ),
        row_index=False,
    )

    _type_shield = _type_factory(
        data_file='ShieldTypes.dat',
        data_mapping=(
            ('Block', {
                'template': 'block',
            }),
        ),
        row_index=True,
    )

    def _apply_flask_buffs(self, infobox, base_item_type, flasks):
        for i, value in enumerate(flasks['BuffStatValues'], start=1):
            infobox['buff_value%s' % i] = value

        if flasks['BuffDefinitionsKey']:
            stats = [s['Id'] for s in flasks['BuffDefinitionsKey']['StatsKeys']]
            tr = self.tc['stat_descriptions.txt'].get_translation(
                stats, flasks['BuffStatValues'], full_result=True
            )
            infobox['buff_stat_text'] = '<br>'.join([
                parser.make_inter_wiki_links(line) for line in tr.lines
            ])


    #TODO: BuffDefinitionsKey, BuffStatValues
    _type_flask = _type_factory(
        data_file='Flasks.dat',
        data_mapping=(
            ('LifePerUse', {
                'template': 'flask_life',
                'condition': lambda v: v > 0,
            }),
            ('ManaPerUse', {
                'template': 'flask_mana',
                'condition': lambda v: v > 0,
            }),
            ('RecoveryTime', {
                'template': 'flask_duration',
                'condition': lambda v: v > 0,
                'format': lambda v: '{0:n}'.format(v / 10),
            }),
            ('BuffDefinitionsKey', {
                'template': 'buff_id',
                'condition': lambda v: v is not None,
                'format': lambda v: v['Id'],
            }),
        ),
        row_index=True,
        function=_apply_flask_buffs,
    )

    _type_flask_charges = _type_factory(
        data_file='ComponentCharges.dat',
        data_mapping=(
            ('MaxCharges', {
                'template': 'charges_max',
            }),
            ('PerCharge', {
                'template': 'charges_per_use',
            }),
        ),
        row_index=False,
    )

    _type_weapon = _type_factory(
        data_file='WeaponTypes.dat',
        data_mapping=(
            ('Critical', {
                'template': 'critical_strike_chance',
                'format': lambda v: '{0:n}'.format(v / 100),
            }),
            ('Speed', {
                'template': 'attack_speed',
                'format': lambda v: '{0:n}'.format(round(1000 / v, 2)),
            }),
            ('DamageMin', {
                'template': 'physical_damage_min',
            }),
            ('DamageMax', {
                'template': 'physical_damage_max',
            }),
            ('RangeMax', {
                'template': 'range',
            }),
        ),
        row_index=True,
    )

    def _currency_extra(self, infobox, base_item_type, currency):
        # Add the "shift click to unstack" stuff to currency-ish items
        if currency['Stacks'] > 1 and infobox['class'] not in \
                ('Microtransactions', ):
            if 'help_text' in infobox:
                infobox['help_text'] += '<br>'
            else:
                infobox['help_text'] = ''

            infobox['help_text'] += self.rr['ClientStrings.dat'].index[
                'Id']['ItemDisplayStackDescription']['Text']

        if infobox.get('description'):
            infobox['description'] = parser.parse_and_handle_description_tags(
                rr=self.rr,
                text=infobox['description'],
            )

        return True

    _type_currency = _type_factory(
        data_file='CurrencyItems.dat',
        data_mapping=(
            ('Stacks', {
                'template': 'stack_size',
                'condition': None,
            }),
            ('Description', {
                'template': 'description',
                'condition': lambda v: v,
            }),
            ('Directions', {
                'template': 'help_text',
                'condition': lambda v: v,
            }),
            ('CurrencyTab_StackSize', {
                'template': 'stack_size_currency_tab',
                'condition': lambda v: v > 0,
            }),
            ('CosmeticTypeName', {
                'template': 'cosmetic_type',
                'condition': lambda v: v,
            }),
        ),
        row_index=True,
        function=_currency_extra,
    )

    _master_hideout_doodad_map = (
        ('NPCMasterKey', {
            'template': 'master',
            'format': lambda v: v['NPCsKey']['Name'],
            #'condition': lambda v: v is not None,
        }),
        ('MasterLevel', {
            'template': 'master_level_requirement',
        }),
        ('FavourCost', {
            'template': 'master_favour_cost',
        }),
    )

    def _apply_master_map(self, infobox, base_item_type, hideout):
        if not hideout['IsNonMasterDoodad']:
            _apply_column_map(infobox, self._master_hideout_doodad_map,
                                   hideout)

    _type_hideout_doodad = _type_factory(
        data_file='HideoutDoodads.dat',
        data_mapping=(
            ('IsNonMasterDoodad', {
                'template': 'is_master_doodad',
                'format': lambda v: not v,
            }),
            ('Variation_AOFiles', {
                'template': 'variation_count',
                'format': lambda v: len(v),
            }),
        ),
        row_index=True,
        function=_apply_master_map,
    )

    def _maps_extra(self, infobox, base_item_type, maps):
        if maps['Shaped_AreaLevel'] > 0:
            infobox['map_area_level'] = maps['Shaped_AreaLevel']
        else:
            infobox['map_area_level'] = maps['Regular_WorldAreasKey'][
                'AreaLevel']

    _type_map = _type_factory(
        data_file='Maps.dat',
        data_mapping=(
            ('Tier', {
                'template': 'map_tier',
            }),
            ('Regular_GuildCharacter', {
                'template': 'map_guild_character',
                'condition': lambda v: v,
            }),
            ('Regular_WorldAreasKey', {
                'template': 'map_area_id',
                'format': lambda v: v['Id'],
            }),
            ('Unique_GuildCharacter', {
                'template': 'unique_map_guild_character',
                'condition': lambda v: v != '',
            }),
            ('Unique_WorldAreasKey', {
                'template': 'unique_map_area_id',
                'format': lambda v: v['Id'],
                'condition': lambda v: v is not None,
            }),
            ('Unique_WorldAreasKey', {
                'template': 'unique_map_area_level',
                'format': lambda v: v['AreaLevel'],
                'condition': lambda v: v is not None,
            }),
        ),
        row_index=True,
        function=_maps_extra,
    )

    def _essence_extra(self, infobox, base_item_type, essence):
        infobox['is_essence'] = True

        # ClientString is outdated. They're building the description from the
        # mod keys it seems.

        if essence['ClientStringsKey']:
            infobox['description'] += '<br />' + essence['ClientStringsKey'][
                'Text'].replace('\n', '<br />').replace('\r', '')

        return True

    _type_essence = _type_factory(
        data_file='Essences.dat',
        data_mapping=(
            ('DropLevelMinimum', {
                'template': 'drop_level',
            }),
            ('DropLevelMaximum', {
                'template': 'drop_level_maximum',
                'condition': lambda v: v > 0,
            }),
            ('ItemLevelRestriction', {
                'template': 'essence_level_restriction',
                'condition': lambda v: v > 0,
            }),
            ('Tier', {
                'template': 'essence_tier',
                'condition': lambda v: v > 0,
            }),
            ('Monster_ModsKeys', {
                'template': 'essence_monster_modifier_ids',
                'format': lambda v: ', '.join([m['Id'] for m in v]),
                'condition': lambda v: v,
            }),
        ),
        row_index=True,
        function=_essence_extra,
        fail_condition=True,
    )

    _type_labyrinth_trinket = _type_factory(
        data_file='LabyrinthTrinkets.dat',
        data_mapping=(
            ('Buff_BuffDefinitionsKey', {
                'template': 'description',
                'format': lambda v: v['Description'],
            }),
        ),
        row_index=True
    )

    _cls_map = {
        # Jewellery
        'Amulets': (_type_amulet, ),
        # Armour types
        'Gloves': (_type_level, _type_attribute, _type_armour, ),
        'Boots': (_type_level, _type_attribute, _type_armour, ),
        'Body Armours': (_type_level, _type_attribute, _type_armour, ),
        'Helmets': (_type_level, _type_attribute, _type_armour, ),
        'Shields': (_type_level, _type_attribute, _type_armour, _type_shield),
        # Weapons
        'Claws': (_type_level, _type_attribute, _type_weapon, ),
        'Daggers': (_type_level, _type_attribute, _type_weapon, ),
        'Wands': (_type_level, _type_attribute, _type_weapon, ),
        'One Hand Swords': (_type_level, _type_attribute, _type_weapon, ),
        'Thrusting One Hand Swords': (
            _type_level, _type_attribute, _type_weapon,
        ),
        'One Hand Axes': (_type_level, _type_attribute, _type_weapon, ),
        'One Hand Maces': (_type_level, _type_attribute, _type_weapon, ),
        'Bows': (_type_level, _type_attribute, _type_weapon, ),
        'Staves': (_type_level, _type_attribute, _type_weapon, ),
        'Two Hand Swords': (_type_level, _type_attribute, _type_weapon, ),
        'Two Hand Axes': (_type_level, _type_attribute, _type_weapon, ),
        'Two Hand Maces': (_type_level, _type_attribute, _type_weapon, ),
        'Sceptres': (_type_level, _type_attribute, _type_weapon, ),
        'Fishing Rods': (_type_level, _type_attribute, _type_weapon, ),
        # Flasks
        'Life Flasks': (_type_level, _type_flask, _type_flask_charges),
        'Mana Flasks': (_type_level, _type_flask, _type_flask_charges),
        'Hybrid Flasks': (_type_level, _type_flask, _type_flask_charges),
        'Utility Flasks': (_type_level, _type_flask, _type_flask_charges),
        'Critical Utility Flasks': (_type_level, _type_flask,
                                    _type_flask_charges),
        # Gems
        'Active Skill Gems': (_skill_gem, ),
        'Support Skill Gems': (_skill_gem, ),
        # Currency-like items
        'Currency': (_type_currency, ),
        'Stackable Currency': (_type_currency, _type_essence),
        'Hideout Doodads': (_type_currency, _type_hideout_doodad),
        'Microtransactions': (_type_currency, ),
        'Divination Card': (_type_currency, ),
        # Labyrinth stuff
        #'Labyrinth Item': (),
        'Labyrinth Trinket': (_type_labyrinth_trinket, ),
        #'Labyrinth Map Item': (),
        # Misc
        'Maps': (_type_map,),
        #'Map Fragments': (_type_,),
        'Quest Items': (),
    }

    _conflict_boots_map = {
        'Metadata/Items/Armours/Boots/BootsAtlas1':
            ' (Cold and Lightning Resistance)',
        'Metadata/Items/Armours/Boots/BootsAtlas2':
            ' (Fire and Cold Resistance)',
        'Metadata/Items/Armours/Boots/BootsAtlas3':
            ' (Fire and Lightning Resistance)',
        # Legion Boots
        'Metadata/Items/Armours/Boots/BootsStrInt7':
            '',
    }

    def _conflict_boots(self, infobox, base_item_type):
        appendix = self._conflict_boots_map.get(
            base_item_type['Id'])
        if appendix is None:
            return
        else:
            infobox['inventory_icon'] = base_item_type['Name'] + appendix
            return base_item_type['Name'] + appendix

    _conflict_quivers_map = {
        'Metadata/Items/Quivers/QuiverDescent': ' (Descent)'
    }

    _conflict_quivers = _simple_conflict_factory(_conflict_quivers_map)

    _conflict_amulet_id_map = {
        'Metadata/Items/Amulets/Talismans/Talisman2_6_1':
            ' (Fire Damage taken as Cold Damage)',
        'Metadata/Items/Amulets/Talismans/Talisman2_6_2':
            ' (Fire Damage taken as Lightning Damage)',
        'Metadata/Items/Amulets/Talismans/Talisman2_6_3':
            ' (Cold Damage taken as Fire Damage)',
        'Metadata/Items/Amulets/Talismans/Talisman2_6_4':
            ' (Cold Damage taken as Lightning Damage)',
        'Metadata/Items/Amulets/Talismans/Talisman2_6_5':
            ' (Lightning Damage taken as Cold Damage)',
        'Metadata/Items/Amulets/Talismans/Talisman2_6_6':
            ' (Lightning Damage taken as Fire Damage)',
        'Metadata/Items/Amulets/Talismans/Talisman3_6_1':
            '  (Power Charge on Kill)',
        'Metadata/Items/Amulets/Talismans/Talisman3_6_2':
            '  (Frenzy Charge on Kill)',
        'Metadata/Items/Amulets/Talismans/Talisman3_6_3':
            '  (Endurance Charge on Kill)',
    }

    def _conflict_amulets(self, infobox, base_item_type):
        appendix = self._conflict_amulet_id_map.get(base_item_type['Id'])
        if appendix is None:
            return base_item_type['Name']
        else:
            return base_item_type['Name'] + appendix

    _conflict_active_skill_gems_map = {
        'Metadata/Items/Gems/SkillGemArcticArmour': True,
        'Metadata/Items/Gems/SkillGemPhaseRun': True,
        'Metadata/Items/Gems/SkillGemLightningTendrils': True,
    }

    def _conflict_active_skill_gems(self, infobox, base_item_type):
        appendix = self._conflict_active_skill_gems_map.get(
            base_item_type['Id'])
        if appendix is None:
            return
        else:
            return base_item_type['Name']

    _conflict_quest_item_id_map = {
        'Metadata/Items/QuestItems/GoldenPages/Page1':
            ' (1 of 4)',
        'Metadata/Items/QuestItems/GoldenPages/Page2':
            ' (2 of 4)',
        'Metadata/Items/QuestItems/GoldenPages/Page3':
            ' (3 of 4)',
        'Metadata/Items/QuestItems/GoldenPages/Page4':
            ' (4 of 4)',
        'Metadata/Items/QuestItems/MapUpgrades/MapUpgradeTier8_1':
            ' (1 of 2)',
        'Metadata/Items/QuestItems/MapUpgrades/MapUpgradeTier8_2':
            ' (2 of 2)',
        'Metadata/Items/QuestItems/MapUpgrades/MapUpgradeTier9_1':
            ' (1 of 3)',
        'Metadata/Items/QuestItems/MapUpgrades/MapUpgradeTier9_2':
            ' (2 of 3)',
        'Metadata/Items/QuestItems/MapUpgrades/MapUpgradeTier9_3':
            ' (3 of 3)',
        'Metadata/Items/QuestItems/MapUpgrades/MapUpgradeTier10_1':
            ' (1 of 3)',
        'Metadata/Items/QuestItems/MapUpgrades/MapUpgradeTier10_2':
            ' (2 of 3)',
        'Metadata/Items/QuestItems/MapUpgrades/MapUpgradeTier10_3':
            ' (3 of 3)',
    }

    def _conflict_quest_items(self, infobox, base_item_type):
        name = base_item_type['Name']
        if name in ('Book of Skill', 'Book of Regrets', 'Book of Reform'):
            qid = base_item_type['Id'].replace('Metadata/Items/QuestItems/', '')
            # Regular quest skill books
            match = re.match(r'(?:SkillBooks|Act[0-9]+)/Book-(?P<id>.*)', qid)
            if match:
                qid = match.group('id')
                ver = re.findall(r'v[0-9]$', qid)
                # Only need one of the skill books from "choice" quets
                if ver:
                    if ver[0] != 'v0':
                        return
                    qid = qid.replace(ver[0], '')

                try:
                    return base_item_type['Name'] + ' (%s)' % \
                           self.rr['Quest.dat'].index['Id'][qid]['Name']
                except KeyError:
                    console('Quest %s not found' % qid, msg=Msg.error)

            # Descent skill books
            match = re.match(r'SkillBooks/Descent2_(?P<id>[0-9]+)', qid)
            if match:
                return base_item_type['Name'] + ' (Descent %s)' % match.group('id')

            # Bandit respec
            match = re.match(r'SkillBooks/BanditRespec(?P<id>.+)', qid)
            if match:
                return base_item_type['Name'] + ' (%s)' % match.group('id')
        elif name == 'Firefly':
            match = re.match(
                r'Metadata/Items/QuestItems/Act7/Firefly(?P<id>[0-9]+)$',
                base_item_type['Id']
            )
            pageid = base_item_type['Name'] + ' (%s of 7)' % match.group('id')
            infobox['inventory_icon'] = pageid
            return pageid
        elif 'Shaper\'s Orb' in name:
            infobox['inventory_icon'] = 'Shaper\'s Orb'


        appendix = self._conflict_quest_item_id_map.get(base_item_type['Id'])
        if appendix is None:
            return
        else:
            if not base_item_type['Id'].startswith('Metadata/Items/QuestItems/'
                                                   'MapUpgrades/'):
                infobox['inventory_icon'] = base_item_type['Name'] + appendix
            return base_item_type['Name'] + appendix

    def _conflict_hideout_doodad(self, infobox, base_item_type):
        try:
            ho = self.rr['HideoutDoodads.dat'].index[
                'BaseItemTypesKey'][base_item_type.rowid]
        except KeyError:
            return

        # This is not perfect, but works currently.
        if ho['NPCMasterKey']:
            if base_item_type['Id'].startswith('Metadata/Items/Hideout/Hideout'
                                               'Wounded'):
                return '%s (%s %s decoration, %s)' % (
                    base_item_type['Name'],
                    ho['NPCMasterKey']['NPCsKey']['ShortName'],
                    ho['MasterLevel'],
                    base_item_type['Id'].replace('Metadata/Items/Hideout/Hideout'
                                                 'Wounded', '')
                )

            return '%s (%s %s decoration)' % (
                base_item_type['Name'],
                ho['NPCMasterKey']['NPCsKey']['ShortName'],
                ho['MasterLevel']
            )
        elif base_item_type['Id'].startswith(
                'Metadata/Items/Hideout/HideoutTotemPole'):
            # Ingore the test doodads on purpose
            if base_item_type['Id'].endswith('Test'):
                return

            match = re.search(
                '(?<=in the )(.*)(?= Leagues)', infobox['help_text']
            )

            if match:
                league = match.group(0)
                if league.endswith('Challenge'):
                    league = league.replace(' Challenge', '')

                return '%s (%s)' % (base_item_type['Name'], league)

    def _conflict_maps(self, infobox, base_item_type):
        id = base_item_type['Id'].replace('Metadata/Items/Maps/', '')
        # Legacy maps
        map_version = None
        for row in self.rr['MapSeries.dat']:
            if not id.startswith(row['Id']):
                continue
            map_version = row['Name']

        if 'Harbinger' in id:
            name = '%s (%s Tier) (%s)' % (
                base_item_type['Name'],
                re.sub(r'^.*Harbinger', '', id),
                map_version,
            )
        else:
            name = '%s (%s)' % (
                base_item_type['Name'],
                map_version
            )

        # Each iteration of maps has it's own art
        infobox['inventory_icon'] = name
        if not id.startswith('MapWorld'):
            infobox['drop_enabled'] = False

        return name

    _conflict_microtransactions_map = {
        'Metadata/Items/MicrotransactionCurrency/MysteryBox1x1':
            ' (1x1)',
        'Metadata/Items/MicrotransactionCurrency/MysteryBox1x2':
            ' (1x2)',
        'Metadata/Items/MicrotransactionCurrency/MysteryBox1x3':
            ' (1x3)',
        'Metadata/Items/MicrotransactionCurrency/MysteryBox1x4':
            ' (1x4)',
        'Metadata/Items/MicrotransactionCurrency/MysteryBox2x1':
            ' (2x1)',
        'Metadata/Items/MicrotransactionCurrency/MysteryBox2x2':
            ' (2x2)',
        'Metadata/Items/MicrotransactionCurrency/MysteryBox2x3':
            ' (2x3)',
        'Metadata/Items/MicrotransactionCurrency/MysteryBox2x4':
            ' (2x4)',
        'Metadata/Items/MicrotransactionCurrency/MysteryBox3x2':
            ' (3x2)',
        'Metadata/Items/MicrotransactionCurrency/MysteryBox3x3':
            ' (3x3)',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionIronMaiden':
        '',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionInfernalAxe'
        : ' (Weapon Skin)',
        'Metadata/Items/MicrotransactionItemEffects/MicrotransactionColossus'
        'Sword': '',
        'Metadata/Items/MicrotransactionItemEffects/Microtransaction'
        'LegionBoots': ' (microtransaction)',
        'Metadata/Items/MicrotransactionItemEffects/Microtransaction'
        'LegionGloves': ' (microtransaction)',
        'Metadata/Items/MicrotransactionItemEffects/Microtransaction'
        'ScholarBoots': ' (microtransaction)',
    }

    def _conflict_microtransactions(self, infobox, base_item_type):
        appendix = self._conflict_microtransactions_map.get(
            base_item_type['Id'])
        if appendix is None:
            return
        else:
            infobox['inventory_icon'] = base_item_type['Name'] + appendix
            return base_item_type['Name'] + appendix

    _conflict_piece_map = {
        'Metadata/Items/UniqueFragments/FragmentUniqueShield1_1':
            ' (1 of 4)',
        'Metadata/Items/UniqueFragments/FragmentUniqueShield1_2':
            ' (2 of 4)',
        'Metadata/Items/UniqueFragments/FragmentUniqueShield1_3':
            ' (3 of 4)',
        'Metadata/Items/UniqueFragments/FragmentUniqueShield1_4':
            ' (4 of 4)',
        'Metadata/Items/UniqueFragments/FragmentUniqueSword1_1':
            ' (1 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueSword1_2':
            ' (2 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueSword1_3':
            ' (3 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueStaff1_1':
            ' (1 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueStaff1_2':
            ' (2 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueStaff1_3':
            ' (3 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueBelt1_1':
            ' (1 of 2)',
        'Metadata/Items/UniqueFragments/FragmentUniqueBelt1_2':
            ' (2 of 2)',
        'Metadata/Items/UniqueFragments/FragmentUniqueQuiver1_1':
            ' (1 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueQuiver1_2':
            ' (2 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueQuiver1_3':
            ' (3 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueHelmet1_1':
            ' (1 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueHelmet1_2':
            ' (2 of 3)',
        'Metadata/Items/UniqueFragments/FragmentUniqueHelmet1_3':
            ' (3 of 3)',
    }

    def _conflict_piece(self, infobox, base_item_type):
        appendix = self._conflict_piece_map.get(
            base_item_type['Id'])
        if appendix is None:
            return
        else:
            infobox['inventory_icon'] = base_item_type['Name'] + appendix
            return base_item_type['Name'] + appendix

    _conflict_resolver_map = {
        'Boots': _conflict_boots,
        'Quivers': _conflict_quivers,
        'Amulets': _conflict_amulets,
        'Active Skill Gems': _conflict_active_skill_gems,
        'Quest Items': _conflict_quest_items,
        'Hideout Doodads': _conflict_hideout_doodad,
        'Maps': _conflict_maps,
        'Microtransactions': _conflict_microtransactions,
        'Piece': _conflict_piece,
    }

    def _parse_class_filter(self, parsed_args):
        self.rr['ItemClasses.dat'].build_index('Name')
        if parsed_args.item_class:
            return [self.rr['ItemClasses.dat'].index['Name'][cls][0]
                   for cls in parsed_args.item_class]
        else:
            return []

    def by_name(self, parsed_args):
        self.rr['BaseItemTypes.dat'].build_index('Name')
        classes = self._parse_class_filter(parsed_args)

        if parsed_args.is_metadata_id:
            items = [
                self.rr['BaseItemTypes.dat'].index['Id'][itemid] for itemid
                in parsed_args.item
            ]
        else:
            items = []
            for itemid in parsed_args.item:
                items.extend(self.rr['BaseItemTypes.dat'].index['Name'][itemid])

        # apply class filter
        if classes:
            items = [
                item for item in items if item['ItemClassesKey'] in classes
            ]

        return self._export(items, parsed_args)

    def by_filter(self, parsed_args):
        classes = self._parse_class_filter(parsed_args)

        if parsed_args.re_name:
            parsed_args.re_name = re.compile(parsed_args.re_name,
                                             flags=re.UNICODE)
        if parsed_args.re_id:
            parsed_args.re_id = re.compile(parsed_args.re_id, flags=re.UNICODE)

        items = []

        for item in self.rr['BaseItemTypes.dat']:
            if classes and not item['ItemClassesKey'] in classes:
                continue

            if parsed_args.re_name and not \
                    parsed_args.re_name.match(item['Name']):
                continue

            if parsed_args.re_id and not \
                    parsed_args.re_id.match(item['Id']):
                continue

            items.append(item)

        return self._export(items, parsed_args)

    def _export(self, items, parsed_args):
        self._parsed_args = parsed_args
        console('Found %s items. Removing disabled items...' % len(items))
        items = [
            base_item_type for base_item_type in items
            if base_item_type['Id'] not in self._SKIP_ITEMS_BY_ID
        ]
        console('%s items left for processing.' % len(items))

        console('Additional files may be loaded. Processing information - this '
                'may take a while...')
        self._image_init(parsed_args)

        r = ExporterResult()
        self.rr['BaseItemTypes.dat'].build_index('Name')

        for base_item_type in items:
            name = base_item_type['Name']
            cls = base_item_type['ItemClassesKey']['Name']

            infobox = OrderedDict()

            infobox['rarity'] = 'Normal'

            # BaseItemTypes.dat
            infobox['name'] = name
            infobox['class'] = cls
            infobox['size_x'] = base_item_type['Width']
            infobox['size_y'] = base_item_type['Height']
            if base_item_type['FlavourTextKey']:
                infobox['flavour_text'] = \
                    parser.parse_and_handle_description_tags(
                        rr=self.rr,
                        text=base_item_type['FlavourTextKey']['Text'],
                    )

            if cls not in self._IGNORE_DROP_LEVEL_CLASSES and \
                    name not in self._IGNORE_DROP_LEVEL_ITEMS:
                infobox['drop_level'] = base_item_type['DropLevel']

            base_ot = OTFile(parent_or_base_dir_or_ggpk=self.base_path)
            base_ot.read(
                self.base_path + '/' + base_item_type['InheritsFrom'] + '.ot')
            try:
                ot = self.ot[base_item_type['Id'] + '.ot']
            except FileNotFoundError:
                pass
            else:
                base_ot.merge(ot)
            finally:
                ot = base_ot

            if 'enable_rarity' in ot['Mods']:
                infobox['drop_rarities'] = ', '.join([
                    n[0].upper() + n[1:] for n in ot['Mods']['enable_rarity']
                ])

            tags = [t['Id'] for t in base_item_type['TagsKeys']]
            infobox['tags'] = ', '.join(tags + list(ot['Base']['tag']))

            infobox['metadata_id'] = base_item_type['Id']

            description = ot['Stack'].get('function_text')
            if description:
                 infobox['description'] = self.rr['ClientStrings.dat'].index[
                     'Id'][description]['Text']

            help_text = ot['Base'].get('description_text')
            if help_text:
                infobox['help_text'] = self.rr['ClientStrings.dat'].index['Id'][
                    help_text]['Text']

            for i, mod in enumerate(base_item_type['Implicit_ModsKeys']):
                infobox['implicit%s' % (i+1)] = mod['Id']

            for rarity in RARITY:
                if rarity.id >= 5:
                    break
                for i, (item, cost) in enumerate(
                        base_item_type[rarity.name_upper + 'Purchase'],
                        start=1):
                    prefix = 'purchase_cost_%s%s' % (rarity.name_lower, i)
                    infobox[prefix + '_name'] = item['Name']
                    infobox[prefix + '_amount'] = cost

            funcs = self._cls_map.get(cls)
            if funcs:
                fail = False
                for f in funcs:
                    if not f(self, infobox, base_item_type):
                        fail = True
                        console(
                            'Required extra info for item "%s" with class "%s"'
                            ' not found. Skipping.' % (name, cls),
                            msg=Msg.error)
                        break
                if fail:
                    continue

            # handle items with duplicate name entries
            # Maps must be handled in any case due to unique naming style of
            # pages
            if cls == 'Maps' or len(self.rr['BaseItemTypes.dat'].index['Name'][name]) > 1:
                resolver = self._conflict_resolver_map.get(cls)

                if resolver:
                    name = resolver(self, infobox, base_item_type)
                    if name is None:
                        console(
                            'Unresolved ambiguous item "%s" with name "%s". '
                            'Skipping' %
                            (base_item_type['Id'], infobox['name']),
                            msg=Msg.error
                        )
                        continue
                else:
                    console('No name conflict handler defined for item class '
                            '"%s"' % cls, msg=Msg.error)
                    continue

            # putting this last since it's usually manually added
            if base_item_type['Name'] in self._DROP_DISABLED_ITEMS or \
                    base_item_type['Id'] in self._DROP_DISABLED_ITEMS_BY_ID:
                infobox['drop_enabled'] = False

            cond = WikiCondition(
                data=infobox,
                cmdargs=parsed_args,
            )

            r.add_result(
                text=cond,
                out_file='item_%s.txt' % name,
                wiki_page=[
                    {
                        'page': name,
                        'condition': cond,
                    }
                ],
                wiki_message='Item exporter',
            )

            if parsed_args.store_images and self.ggpk:
                if not base_item_type['ItemVisualIdentityKey']['DDSFile']:
                    warnings.warn(
                        'Missing 2d art inventory icon for item "%s"' %
                        base_item_type['Name']
                    )
                    continue

                self._write_dds(
                    data=self.ggpk[base_item_type['ItemVisualIdentityKey'][
                        'DDSFile']].record.extract().read(),
                    out_path=os.path.join(self._img_path, (
                        infobox.get('inventory_icon') or name) +
                        ' inventory icon.dds',
                    ),
                    parsed_args=parsed_args,
                )

        return r

    _conflict_resolver_prophecy_map = {
        'MapExtraHaku': ' (Haku)',
        'MapExtraTora': ' (Tora)',
        'MapExtraCatarina': ' (Catarina)',
        'MapExtraVagan': ' (Vagan)',
        'MapExtraElreon': ' (Elreon)',
        'MapExtraVorici': ' (Vorici)',
        'MapExtraZana': ' (Zana)',
        # The other one is disabled, should be fine
        'MapSpawnRogueExiles': '',
        'MysteriousInvadersFire': ' (Fire)',
        'MysteriousInvadersCold': ' (Cold)',
        'MysteriousInvadersLightning': ' (Lightning)',
        'MysteriousInvadersPhysical': ' (Physical)',
        'MysteriousInvadersChaos': ' (Chaos)',

        'AreaAllRaresAreCloned': ' (prophecy)',
        'HillockDropsTheAnvil': ' (prophecy)',
    }

    def prophecy(self, parsed_args):
        self.rr['Prophecies.dat'].build_index('Name')
        prophecies = []
        names = defaultdict(list)
        for prophecy in self.rr['Prophecies.dat']:
            name = prophecy['Name']
            names[name].append(prophecy)
            if name not in parsed_args.name:
                continue

            if not prophecy['IsEnabled'] and not parsed_args.allow_disabled:
                console(
                    'Prophecy "%s" is disabled - skipping.' % name,
                    msg=Msg.error
                )
                continue

            prophecies.append(prophecy)

        r = ExporterResult()
        for prophecy in prophecies:
            name = prophecy['Name']

            infobox = OrderedDict()

            infobox['rarity'] = 'Normal'
            infobox['name'] = name
            infobox['class'] = 'Stackable Currency'
            infobox['base_item_page'] = 'Prophecy'
            infobox['flavour_text'] = prophecy['FlavourText']
            infobox['prophecy_id'] = prophecy['Id']
            infobox['prediction_text'] = prophecy['PredictionText']
            infobox['seal_cost'] = prophecy['SealCost']

            if not prophecy['IsEnabled']:
                infobox['drop_enabled'] = False

            # handle items with duplicate name entries
            if len(names[name]) > 1:
                extra = self._conflict_resolver_prophecy_map.get(prophecy['Id'])
                if extra is None:
                    console('Unresolved ambiguous item name "%s" / id "%s". '
                            'Skipping' % (prophecy['Name'], prophecy['Id']),
                            msg=Msg.error)
                    continue
                name += extra
            cond = WikiCondition(
                data=infobox,
                cmdargs=parsed_args,
            )

            r.add_result(
                text=cond,
                out_file='item_%s.txt' % name,
                wiki_page=[
                    {'page': name, 'condition': cond},
                    {'page': name + ' (prophecy)', 'condition': cond},
                ],
                wiki_message='Prophecy exporter',
            )

        return r
