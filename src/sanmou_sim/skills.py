from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from typing import Any, Protocol

from .models import DamageKind, General, Modifier, SkillTiming, StatusEffect, Team


class BattleApi(Protocol):
    round_no: int
    rng: Random

    def enemies_of(self, actor: General) -> Team: ...
    def allies_of(self, actor: General) -> Team: ...
    def log_event(self, message: str) -> None: ...
    def record_activation(self, actor: General, source: str) -> None: ...
    def consume_trigger(self, actor: General, source: str, event: str, limit: int | None = None) -> bool: ...
    def trigger_count(self, actor: General, source: str, event: str) -> int: ...
    def event_count(self, actor: General, event: str) -> int: ...
    def deal_damage(
        self,
        actor: General,
        target: General,
        power: float,
        kind: DamageKind,
        source: str,
        *,
        effect_owner: General | None = None,
        damage_context: dict[str, Any] | None = None,
    ) -> int: ...
    def heal(self, actor: General, target: General, power: float, source: str) -> int: ...
    def settle_deserters(self, actor: General, target: General, amount: int, source: str) -> int: ...
    def damage_taken_reduction_total(
        self,
        target: General,
        kind: DamageKind | None = None,
        timing: str | None = None,
    ) -> float: ...
    def heal_fixed(self, actor: General, target: General, amount: int, source: str, is_extra: bool = False) -> int: ...
    def pick_damage_targets(self, actor: General, count: int) -> list[General]: ...
    def pick_targets(self, team: Team, count: int, exclude: General | None = None) -> list[General]: ...
    def perform_basic_attack(self, actor: General, target: General | None = None, ignore_disarm: bool = False) -> int: ...
    def cast_skill(self, actor: General, skill_name: str) -> bool: ...
    def force_cast_skill(self, actor: General, skill_name: str, context: dict[str, Any] | None = None) -> bool: ...
    def on_status_applied(self, actor: General, target: General, status_name: str) -> None: ...
    def on_attribute_reduced(self, actor: General, target: General, source_skill: str) -> None: ...
    def on_attribute_changed(
        self,
        target: General,
        stat: str,
        previous: float,
        current: float,
        source_skill: str | None = None,
    ) -> None: ...
    def trigger_named_event(self, actor: General, name: str, context: dict[str, Any] | None = None) -> None: ...


STAT_NAME_MAP = {
    "武力": "force",
    "智力": "intellect",
    "统率": "command",
    "先攻": "initiative",
}
OFFICIAL_ATTRIBUTE_STATS = frozenset(STAT_NAME_MAP.values())

SKILL_TYPE_TIMING = {
    "被动": SkillTiming.PASSIVE,
    "指挥": SkillTiming.COMMAND,
    "主动": SkillTiming.ACTIVE,
    "追击": SkillTiming.PURSUIT,
}

CONTROL_STATUSES = ["震慑", "技穷", "缴械", "混乱", "嘲讽", "虚弱", "断粮"]
ABNORMAL_STATUSES = CONTROL_STATUSES + ["洪水", "火攻", "风暴", "畏惧", "妖术"]
KNOWN_STATUSES = CONTROL_STATUSES + [
    "焚烧", "中毒", "流血", "鸩毒", "迟滞", "凶逆", "应变", "连环", "暗事",
    "畏惧", "火攻", "洪水", "风暴", "妖术", "抵御", "必中", "清醒",
]
LAYOUT_STATES = [f"布阵{number}" for number in "一二三四五六七八"]


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    timing: SkillTiming
    chance: float
    effect: str
    power: float = 1.0
    targets: int = 1
    duration: int = 1
    prepare_rounds: int = 0
    status_name: str = ""
    raw_text: str = ""
    traits: tuple[str, ...] = ()
    data_effects: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    max_triggers_per_round: int = 0

    def apply_setup(self, api: BattleApi, actor: General) -> bool:
        effects = tuple(effect for effect in self.data_effects if _effect_matches_event(effect, "setup", self.timing))
        if self.effect != "generic":
            return self.try_cast(api, actor)
        if not effects or not actor.is_alive:
            return False
        api.record_activation(actor, self.name)
        api.log_event(f"{actor.name} 的 {self.name} 生效")
        return self._cast_generic(api, actor, effects=effects, event="setup")

    def trigger(self, api: BattleApi, actor: General, event: str, context: dict[str, Any]) -> bool:
        if self.effect != "generic" or not actor.is_alive:
            return False
        effects = tuple(effect for effect in self.data_effects if _effect_matches_event(effect, event, self.timing))
        if not effects or not _event_owner_matches(actor, event, context, effects):
            return False

        max_triggers = self.max_triggers_per_round or max(
            (int(effect.get("max_triggers_per_round", 0) or 0) for effect in effects),
            default=0,
        )
        if max_triggers and api.trigger_count(actor, self.name, "round_limit") >= max_triggers:
            return False
        api.consume_trigger(actor, self.name, event)

        selected: list[dict[str, Any]] = []
        chance_prechecked: set[int] = set()
        for effect in effects:
            if not _round_condition_allows(effect, api.round_no):
                continue
            if not _event_condition_allows(api, actor, self.name, effect, event, context):
                continue
            if self.name == "机变无穷" and selected:
                chance_prechecked.add(id(effect))
                selected.append(effect)
                continue
            if not _uses_per_target_chance(effect):
                chance_reduction = float(effect.get("per_trigger_chance_reduction_current_round", 0.0) or 0.0)
                if chance_reduction:
                    successful = api.trigger_count(actor, self.name, f"{event}:chance_success")
                    chance = max(0.0, _effect_trigger_chance(effect, api.round_no, actor) - chance_reduction * successful)
                    passed = chance >= 1.0 or api.rng.random() < chance
                else:
                    passed = _roll_effect(api, effect, actor)
                if not passed:
                    continue
                if chance_reduction:
                    api.consume_trigger(actor, self.name, f"{event}:chance_success")
                chance_prechecked.add(id(effect))
            selected.append(effect)
        if not selected:
            return False

        if max_triggers:
            api.consume_trigger(actor, self.name, "round_limit", max_triggers)

        api.record_activation(actor, self.name)
        api.log_event(f"{actor.name} 触发 {self.name}")
        cast_context = dict(context)
        cast_context["chance_prechecked"] = chance_prechecked
        result = self._cast_generic(api, actor, effects=tuple(selected), event=event, context=cast_context)
        context.update(cast_context)
        trigger_names = {
            str(effect.get("trigger_name", ""))
            for effect in selected
            if effect.get("trigger_name") and effect.get("kind") != "trigger_named_effect"
        }
        for trigger_name in trigger_names:
            api.trigger_named_event(actor, trigger_name, context)
        return result

    def try_cast(self, api: BattleApi, actor: General) -> bool:
        chance = max(0.0, min(1.0, self.chance + actor.modifier_total(f"{self.timing.value}_chance_bonus")))
        if not actor.is_alive or api.rng.random() > chance:
            return False

        api.record_activation(actor, self.name)
        api.log_event(f"{actor.name} 发动 {self.name}")

        if self.effect != "generic":
            return self._cast_legacy(api, actor)
        return self._cast_generic(api, actor, event="cast")

    def _cast_legacy(self, api: BattleApi, actor: General) -> bool:
        if self.effect == "weapon_damage":
            for target in api.pick_damage_targets(actor, self.targets):
                api.deal_damage(actor, target, self.power, DamageKind.WEAPON, self.name)
            return True

        if self.effect == "strategy_damage":
            for target in api.pick_damage_targets(actor, self.targets):
                api.deal_damage(actor, target, self.power, DamageKind.STRATEGY, self.name)
            return True

        if self.effect == "heal":
            wounded = [general for general in api.allies_of(actor).alive_generals if general.troops < general.healable_max_troops()]
            for target in sorted(wounded, key=lambda general: general.troops / general.max_troops)[: self.targets]:
                api.heal(actor, target, self.power, self.name)
            return bool(wounded)

        if self.effect == "reduce_enemy_command":
            for target in api.pick_targets(api.enemies_of(actor), self.targets):
                amount = -max(8.0, actor.stat("force") * self.power * 0.12)
                target.modifiers.append(
                    Modifier(
                        self.name,
                        "command",
                        amount,
                        api.round_no + self.duration,
                        source_actor=actor.name,
                        source_skill=self.name,
                        source_timing=self.timing,
                    )
                )
                api.log_event(f"{actor.name} 发动 {self.name}，{target.name} 统率 {amount:.0f}")
            return True

        if self.effect == "team_damage_reduction":
            self._apply_modifier(api, actor, api.allies_of(actor).alive_generals, "damage_taken_reduction", self.power)
            api.log_event(f"{actor.name} 发动 {self.name}，己方获得减伤 {self.power:.0%}")
            return True

        if self.effect == "team_damage_bonus":
            self._apply_modifier(api, actor, api.allies_of(actor).alive_generals, "damage_dealt_bonus", self.power)
            api.log_event(f"{actor.name} 发动 {self.name}，己方增伤 {self.power:.0%}")
            return True

        if self.effect == "apply_status":
            for target in api.pick_targets(api.enemies_of(actor), self.targets):
                self._add_status(api, target, actor, self.status_name, self.duration)
                api.log_event(f"{target.name} 获得 {self.status_name}")
            return True

        api.log_event(f"{actor.name} 的 {self.name} 暂未实现效果")
        return False

    def _cast_generic(
        self,
        api: BattleApi,
        actor: General,
        effects: tuple[dict[str, Any], ...] | None = None,
        event: str = "cast",
        context: dict[str, Any] | None = None,
    ) -> bool:
        did_anything = False
        did_damage = False
        did_heal = False
        context = context if context is not None else {}
        context["_target_cache"] = {}
        selected_effects = effects or tuple(
            effect for effect in self.data_effects if _effect_matches_event(effect, event, self.timing)
        )
        priority = next((effect for effect in selected_effects if effect.get("kind") == "target_priority"), None)
        if priority is not None and _roll_effect_for_target(api, priority, actor=actor):
            context["prefer_back"] = True
        preexisting_statuses = {
            id(target): {status.name for status in target.statuses}
            for target in api.enemies_of(actor).alive_generals + api.allies_of(actor).alive_generals
        }

        def refresh_target_statuses(target: General) -> None:
            if not context.get("_per_target_pass"):
                preexisting_statuses[id(target)] = {status.name for status in target.statuses}

        grouped_indices: set[int] = set()
        for effect_index, effect in enumerate(selected_effects):
            if effect_index in grouped_indices:
                continue
            if not context.get("_per_target_pass"):
                group_end = self._target_sequence_end(selected_effects, effect_index)
                if group_end > effect_index + 1:
                    group = selected_effects[effect_index:group_end]
                    first_target = str(effect.get("target", ""))
                    targets = self._select_targets(
                        api, actor, first_target,
                        enemy_default="敌军" in first_target or "敌我" in first_target,
                        context=context,
                    )
                    if len(targets) > 1:
                        checked = set(context.get("chance_prechecked", set()))
                        eligible = []
                        for item in group:
                            if _uses_per_target_chance(item) or id(item) in checked:
                                eligible.append(item)
                            elif _roll_effect(api, item, actor):
                                checked.add(id(item))
                                eligible.append(item)
                        for target in targets:
                            if not actor.is_alive:
                                break
                            target_context = {
                                **context,
                                "_per_target_pass": True,
                                "_target_override": target,
                                "_target_override_texts": {str(item.get("target", "")) for item in group},
                                "last_targets": [target],
                                "chance_prechecked": checked,
                            }
                            if eligible:
                                self._cast_generic(api, actor, effects=tuple(eligible), event=event, context=target_context)
                            context["damage"] = target_context.get("damage", context.get("damage", 0))
                            context["last_targets"] = [target]
                        grouped_indices.update(range(effect_index + 1, group_end))
                        did_anything = True
                        continue
            context.pop("_condition_reference", None)
            kind = str(effect.get("kind", ""))
            target_text = str(effect.get("target", ""))
            target_priority = str(effect.get("target_priority", ""))
            if target_priority:
                context["prefer_back"] = "后排" in target_priority or ("同排" in target_priority and actor.position == "back")
                context["prefer_front"] = "前排" in target_priority or "同排" in target_priority and actor.position == "front"
            chance_prechecked = context.get("chance_prechecked", set())
            if (
                kind != "target_priority"
                and not _uses_per_target_chance(effect)
                and id(effect) not in chance_prechecked
                and not _roll_effect(api, effect, actor)
            ):
                continue

            if kind in {"weapon_damage", "strategy_damage", "triggered_weapon_damage", "extra_weapon_damage", "follow_up_weapon_damage", "damage", "adaptive_damage"}:
                initial_kind = _damage_kind_for_effect(effect, actor, kind)
                base_power = _number_at_level_10(effect, "damage_rate", fallback=self._fallback_damage_power(initial_kind))
                if effect.get("bonus_per_available_state_at_level_10") is not None:
                    state_count = self._layout_state_count(actor)
                    maximum = int(effect.get("max_bonus_stacks", state_count) or state_count)
                    base_power += _number_at_level_10(effect, "bonus_per_available_state", fallback=0.0) * min(state_count, maximum)
                for growth in self.data_effects:
                    if growth.get("kind") == "skill_damage_rate_increase_per_round":
                        base_power += _number_at_level_10(growth, "value", fallback=0.0) * max(1, api.round_no)
                base_power += float(effect.get("damage_rate_bonus_per_round", 0.0) or 0.0) * max(1, api.round_no)
                base_power -= float(effect.get("damage_rate_reduction_per_round", 0.0) or 0.0) * max(0, api.round_no - 1)
                evasion_bonus = float(effect.get("damage_rate_bonus_per_successful_evasion_this_round", 0.0) or 0.0)
                if evasion_bonus:
                    bonus_cap = float(effect.get("max_damage_rate_bonus", 1.0) or 1.0)
                    base_power += min(bonus_cap, evasion_bonus * api.event_count(actor, "after_evasion"))
                base_power = max(0.0, base_power)
                condition_text = str(effect.get("condition", ""))
                damage_sources = [self._select_damage_source(api, actor, effect)]
                if "我军武将持有笃行" in condition_text:
                    damage_sources = [source for source in api.allies_of(actor).alive_generals if source.has_status("笃行")]
                elif "放权目标每持有1层旨意" in condition_text:
                    damage_sources = [
                        source for source in api.allies_of(actor).alive_generals
                        if source.has_status("放权") and source.has_status("旨意")
                    ]
                for damage_actor in damage_sources:
                    repetitions = max(1, int(effect.get("cast_count", effect.get("trigger_count", 1)) or 1))
                    if "放权目标每持有1层旨意" in condition_text:
                        repetitions = damage_actor.status("旨意").stacks
                    for _ in range(repetitions):
                        context["_force_reselect"] = repetitions > 1 or len(damage_sources) > 1
                        targets = self._select_targets(api, damage_actor, target_text, enemy_default=True, context=context)
                        context["last_targets"] = targets
                        for target in targets:
                            refresh_target_statuses(target)
                            power_bonus = 0.0
                            critical_bonus = 0.0
                            if damage_actor.has_status("笃行"):
                                stacks = damage_actor.status("笃行").stacks
                                sibling = next((item for item in self.data_effects if item.get("kind") == "per_stack_damage_and_crit_bonus"), None)
                                if sibling is not None:
                                    power_bonus = _number_at_level_10(sibling, "damage_rate_bonus", fallback=0.0) * stacks
                                    critical_bonus = _number_at_level_10(sibling, "critical_chance_bonus", fallback=0.0) * stacks
                            damage_kind = _damage_kind_for_effect(effect, damage_actor, kind)
                            condition_target = context.get("_condition_reference", target)
                            if not isinstance(condition_target, General):
                                condition_target = target
                            if not _target_condition_allows(effect, damage_actor, condition_target, preexisting_statuses):
                                continue
                            if _uses_per_target_chance(effect) and not _roll_effect_for_target(api, effect, target, actor):
                                continue
                            power = self._damage_power_for_target(effect, target, base_power + power_bonus, preexisting_statuses)
                            damage_context = self._damage_context_for_target(api, effect, target, preexisting_statuses)
                            damage_context["critical_chance_bonus"] = (
                                float(damage_context.get("critical_chance_bonus", 0.0)) + critical_bonus
                            )
                            dealt = api.deal_damage(
                                damage_actor,
                                target,
                                power,
                                damage_kind,
                                self.name,
                                effect_owner=actor,
                                damage_context=damage_context,
                            )
                            context["damage"] = float(context.get("damage", 0)) + dealt
                            did_anything = True
                            did_damage = True
                    if "放权目标每持有1层旨意" in condition_text and repetitions > 0:
                        damage_actor.consume_status_stack("旨意", repetitions)
                        api.log_event(f"{damage_actor.name} 消耗 {repetitions} 层旨意")
                context.pop("_force_reselect", None)
                continue

            if kind in {"weapon_and_strategy_damage", "strategy_and_weapon_damage"}:
                event_actor = context.get("actor")
                damage_actor = (
                    event_actor
                    if isinstance(event_actor, General) and "施策目标" in str(effect.get("timing", ""))
                    else self._select_damage_source(api, actor, effect)
                )
                selection_text = str(effect.get("target_selector", target_text))
                repetitions = max(1, int(effect.get("times", 1) or 1))
                damage_order = (
                    ((DamageKind.STRATEGY, "strategy_damage_rate"), (DamageKind.WEAPON, "weapon_damage_rate"))
                    if kind == "strategy_and_weapon_damage" else
                    ((DamageKind.WEAPON, "weapon_damage_rate"), (DamageKind.STRATEGY, "strategy_damage_rate"))
                )
                for _ in range(repetitions):
                    lock_chance = float(effect.get("lock_lowest_force_or_intellect_chance", 0.0) or 0.0)
                    if not lock_chance:
                        context["_force_reselect"] = True
                        targets = self._select_targets(api, damage_actor, selection_text, enemy_default=True, context=context)
                        context["last_targets"] = targets
                        for target in targets:
                            refresh_target_statuses(target)
                            for damage_kind, stem in damage_order:
                                if not actor.is_alive or not damage_actor.is_alive or not target.is_alive:
                                    break
                                if _target_condition_allows(effect, damage_actor, target, preexisting_statuses):
                                    power = _number_at_level_10(effect, stem, fallback=_number_at_level_10(effect, "damage_rate", fallback=self._fallback_damage_power(damage_kind)))
                                    dealt = api.deal_damage(damage_actor, target, power, damage_kind, self.name, effect_owner=actor)
                                    context["damage"] = float(context.get("damage", 0)) + dealt
                                    did_anything = True
                                    did_damage = True
                        continue
                    for damage_kind, stem in damage_order:
                        enemies = api.enemies_of(damage_actor).alive_generals
                        if lock_chance > 0 and enemies and api.rng.random() < lock_chance:
                            lock_stat = "force" if damage_kind == DamageKind.WEAPON else "intellect"
                            targets = [min(enemies, key=lambda target: target.stat(lock_stat))]
                        else:
                            context["_force_reselect"] = True
                            targets = self._select_targets(api, damage_actor, selection_text, enemy_default=True, context=context)
                        context["last_targets"] = targets
                        power = _number_at_level_10(effect, stem, fallback=_number_at_level_10(effect, "damage_rate", fallback=self._fallback_damage_power(damage_kind)))
                        for target in targets:
                            refresh_target_statuses(target)
                            if _target_condition_allows(effect, damage_actor, target, preexisting_statuses):
                                dealt = api.deal_damage(damage_actor, target, power, damage_kind, self.name, effect_owner=actor)
                                context["damage"] = float(context.get("damage", 0)) + dealt
                                did_anything = True
                                did_damage = True
                context.pop("_force_reselect", None)
                if "清除施策目标所有武略层数" in str(effect.get("after_effect", "")):
                    if damage_actor.has_status("武略"):
                        self._clear_state_effects(damage_actor, "武略")
                        api.log_event(f"{damage_actor.name} 的「武略」效果已消失")
                continue

            if kind in {"heal", "triggered_heal", "cleanse_and_extra_heal"}:
                power = _calibrated_value(
                    actor,
                    effect,
                    "heal_rate",
                    fallback=self._fallback_heal_power(),
                )
                if effect.get("heal_rate_bonus_per_jushou_stack") is not None:
                    jushou = actor.status("据守")
                    power += float(effect["heal_rate_bonus_per_jushou_stack"]) * (jushou.stacks if jushou else 0)
                targets = self._select_targets(api, actor, target_text or "我军兵力最低单体", enemy_default=False, context=context)
                context["last_targets"] = targets
                for target in targets:
                    if _uses_per_target_chance(effect) and not _roll_effect_for_target(api, effect, target, actor):
                        continue
                    if kind == "cleanse_and_extra_heal":
                        _cleanse_negative_states(target, int(effect.get("cleanse_negative_states", 1) or 1))
                    api.heal(actor, target, power, self.name)
                    did_anything = True
                    did_heal = True
                continue

            if kind in {"apply_state", "grant_state"}:
                state = str(effect.get("state", self.status_name or "状态"))
                if state == "逃兵" and "累积讨伐" in str(effect.get("condition", "")):
                    # 九伐中原在 multi_hit 分支按累计讨伐次数立即结算；这里仅是
                    # 数据中的说明性从属效果，不能再作为独立事件重复结算。
                    did_anything = True
                    continue
                duration = _duration(effect, self.raw_text, self.duration)
                applied_effect = effect
                if effect.get("stacks_per_enemy_outsped") is not None:
                    lower_enemies = sum(
                        actor.stat("initiative") > enemy.stat("initiative")
                        for enemy in api.enemies_of(actor).alive_generals
                    )
                    applied_effect = {
                        **effect,
                        "stacks": lower_enemies * int(effect["stacks_per_enemy_outsped"]),
                    }
                applications = 1
                if "每累计受到" in str(effect.get("condition", "")):
                    applications = max(1, int(context.get("cumulative_trigger_count", 1) or 1))
                for _ in range(applications):
                    if applications > 1:
                        context["_force_reselect"] = True
                    targets = self._select_targets(api, actor, target_text, enemy_default=_is_harmful_state(state), context=context)
                    context["last_targets"] = targets
                    for target in targets:
                        refresh_target_statuses(target)
                        if not _target_condition_allows(effect, actor, target, preexisting_statuses):
                            continue
                        if not _roll_effect_for_target(api, effect, target, actor):
                            continue
                        if state == "逃兵":
                            amount = self._deserter_amount(actor, target, effect)
                            if amount is None:
                                api.log_event(f"{actor.name} 的【{self.name}】逃兵公式待实测拟合，本次暂不结算逃兵")
                                did_anything = True
                                continue
                            api.settle_deserters(actor, target, amount, self.name)
                            did_anything = True
                            continue
                        if state == "伏兵":
                            ratio = _number_at_level_10(
                                effect,
                                "amount_current_troop_ratio",
                                fallback=_number_at_level_10(effect, "amount_ratio", fallback=0.05),
                            )
                            amount = min(1500, int(actor.troops * ratio))
                            self._add_status(api, target, actor, state, duration, {**effect, "amount": amount})
                            current = target.status(state)
                            if current is not None:
                                current.payload["amount"] = amount
                            api.log_event(f"{target.name} 获得 {amount} 伏兵")
                            did_anything = True
                            continue
                        self._add_status(api, target, actor, state, duration, applied_effect)
                        self._apply_named_state_modifier(api, actor, target, state, duration, applied_effect)
                        api.log_event(f"{target.name} 获得 {state}")
                        did_anything = True
                context.pop("_force_reselect", None)
                continue

            if kind in {"stat_bonus", "stat_debuff", "stat_reduction", "steal_stat"}:
                targets = self._select_targets(
                    api,
                    actor,
                    target_text,
                    enemy_default=kind in {"stat_debuff", "stat_reduction", "steal_stat"},
                    context=context,
                )
                decay = float(effect.get("per_round_effect_decay", 0.0) or 0.0)
                duration = _duration(effect, self.raw_text, self.duration)
                for target in targets:
                    refresh_target_statuses(target)
                    stat_values = _stat_values(effect, self.raw_text, actor)
                    recipient = context.get("actor") if effect.get("recipient") == "九锡持有者" else actor
                    if not isinstance(recipient, General) or not recipient.is_alive:
                        recipient = actor
                    reduced_attribute = False
                    for stat, raw_value in stat_values:
                        raw_value *= max(0.0, 1.0 - decay * max(0, api.round_no - 1))
                        raw_value *= float(effect.get("value_multiplier", 1.0))
                        transfer_effect = {**effect, "source_target": target.name}
                        if stat == "最高属性":
                            stat = max(STAT_NAME_MAP.values(), key=target.stat)
                        value = -abs(raw_value) if kind in {"stat_debuff", "stat_reduction", "steal_stat"} or "降低" in str(effect.get("condition", "")) + target_text else raw_value
                        self._apply_modifier(
                            api, actor, [target], stat, value, duration=duration, effect=transfer_effect,
                            notify_attribute_reduction=False,
                        )
                        reduced_attribute |= stat in OFFICIAL_ATTRIBUTE_STATS and value < 0
                        if kind == "steal_stat" and value < 0:
                            self._apply_modifier(api, actor, [recipient], stat, abs(value), duration=duration, effect=transfer_effect)
                    if reduced_attribute:
                        api.on_attribute_reduced(actor, target, self.name)
                if targets:
                    api.log_event(f"{actor.name} 的 {self.name} 改变了 {len(targets)} 个目标的属性")
                    did_anything = True
                continue

            if kind == "follow_up_damage_bonus" and target_text == "该次追伤":
                # Folded into the matching follow-up hit so it never becomes a
                # persistent pursuit-damage modifier.
                did_anything = True
                continue

            modifier_stat = _modifier_stat_from_kind(kind)
            if kind == "critical_chance_bonus" and effect.get("critical_type") == "会心":
                modifier_stat = "weapon_critical_chance"
            elif kind == "critical_chance_bonus" and effect.get("critical_type") == "奇谋":
                modifier_stat = "strategy_critical_chance"
            if modifier_stat:
                def modifier_value() -> float:
                    value = _calibrated_value(actor, effect, "value", fallback=_fallback_modifier_value(self.raw_text, modifier_stat))
                    value *= _learned_skill_condition_multiplier(actor, effect)
                    enemy_state_bonus = effect.get("bonus_per_enemy_state")
                    if isinstance(enemy_state_bonus, dict):
                        state_name = str(enemy_state_bonus.get("state", ""))
                        value += float(enemy_state_bonus.get("value", 0.0) or 0.0) * sum(
                            enemy.has_status(state_name) for enemy in api.enemies_of(actor).alive_generals
                        )
                    return -abs(value) if kind in NEGATIVE_MODIFIER_KINDS else value

                value = modifier_value()
                if target_text in {"本次伤害", "该次伤害", "本次承担伤害", "该次承担伤害"} and event.startswith("before_damage"):
                    if modifier_stat.endswith("damage_taken_reduction") or modifier_stat == "damage_taken_reduction":
                        context.setdefault("current_damage_reductions", []).append(abs(value))
                    elif modifier_stat in {"damage_taken_increase", "damage_taken_reduction_penalty"}:
                        context.setdefault("current_damage_increases", []).append(abs(value))
                    else:
                        context["current_damage_multiplier"] = float(context.get("current_damage_multiplier", 1.0)) * max(0.0, 1.0 + value)
                    did_anything = True
                    continue
                targets = self._select_targets(api, actor, target_text, enemy_default=value < 0, context=context)
                duration = _duration(effect, self.raw_text, self.duration)
                conditional_increase = float(effect.get("effect_increase_if_target_command_higher_than_self", 0.0) or 0.0)
                self_bonus = float(effect.get("self_effect_bonus", 0.0) or 0.0)
                for target in targets:
                    refresh_target_statuses(target)
                    if not _target_condition_allows(effect, actor, target, preexisting_statuses):
                        continue
                    if _uses_per_target_chance(effect) and not _roll_effect_for_target(api, effect, target, actor):
                        continue
                    target_value = modifier_value()
                    if (
                        modifier_stat == "weapon_damage_taken_reduction"
                        and effect.get("bonus_if_allied_race") == "夷族"
                        and _is_yizu(target)
                    ):
                        target_value *= 1.0 + float(effect.get("bonus_effect_increase", 0.0) or 0.0)
                    if conditional_increase and target.stat("command") > actor.stat("command"):
                        target_value *= 1.0 + conditional_increase
                    if self_bonus and target is actor:
                        target_value *= 1.0 + self_bonus
                    self._apply_modifier(
                        api,
                        actor,
                        [target],
                        modifier_stat,
                        target_value,
                        duration=duration,
                        effect=effect,
                    )
                    did_anything = True
                continue

            if self._cast_special_effect(api, actor, effect, event, context):
                did_anything = True
                continue

            raise ValueError(f"战法 {self.name} 存在未实现效果类型: {kind}")

        if not self.data_effects and not did_damage and event == "cast" and self.timing in {SkillTiming.ACTIVE, SkillTiming.PURSUIT}:
            for damage_kind, power in self._damage_actions_from_text():
                for target in api.pick_damage_targets(actor, self._target_count(self.raw_text)):
                    api.deal_damage(actor, target, power, damage_kind, self.name)
                    did_anything = True
                    did_damage = True

        if not self.data_effects and not did_heal and event == "cast" and _looks_like_heal(self.raw_text):
            power = self._fallback_heal_power()
            wounded = [general for general in api.allies_of(actor).alive_generals if general.troops < general.healable_max_troops()]
            targets = sorted(wounded, key=lambda general: general.troops / general.max_troops)[: self._target_count(self.raw_text)]
            for target in targets:
                api.heal(actor, target, power, self.name)
                did_anything = True
                did_heal = True

        if event == "cast" and not self.data_effects:
            did_anything = self._apply_text_modifiers(api, actor) or did_anything
            did_anything = self._apply_text_statuses(api, actor) or did_anything

        if not did_anything:
            api.log_event(f"{actor.name} 的 {self.name} 本次未产生可结算效果")
        return True

    def _target_sequence_end(self, effects: tuple[dict[str, Any], ...], start: int) -> int:
        first = effects[start]
        target = str(first.get("target", ""))
        if not target or self._target_count(target) <= 1:
            return start + 1
        if first.get("source_selector") or int(first.get("cast_count", 1) or 1) > 1 or int(first.get("times", 1) or 1) > 1:
            return start + 1
        aliases = {target, "目标", "敌军目标", "友军目标", "伤害目标", "当前目标", "属性降低目标"}
        end = start + 1
        while end < len(effects):
            item = effects[end]
            item_target = str(item.get("target", ""))
            if item_target not in aliases or item.get("source_selector") or int(item.get("cast_count", 1) or 1) > 1 or int(item.get("times", 1) or 1) > 1:
                break
            end += 1
        return end

    def _cast_special_effect(
        self,
        api: BattleApi,
        actor: General,
        effect: dict[str, Any],
        event: str,
        context: dict[str, Any],
    ) -> bool:
        kind = str(effect.get("kind", ""))
        target_text = str(effect.get("target", ""))
        duration = _duration(effect, self.raw_text, self.duration)

        if kind in {"lifesteal", "lifesteal_bonus", "mutiny_bonus", "lifesteal_and_evasion_bonus"}:
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            if kind == "lifesteal_and_evasion_bonus":
                weapon_value = _number_at_level_10(effect, "lifesteal_bonus", fallback=0.0)
                evasion = _number_at_level_10(effect, "evasion_rate_bonus", fallback=0.0)
                for target in targets:
                    self._apply_modifier(api, actor, [target], "weapon_lifesteal", weapon_value, duration)
                    self._apply_modifier(api, actor, [target], "evasion_chance", evasion, duration)
                return True
            value = _number_at_level_10(effect, "value", fallback=0.0)
            types = effect.get("lifesteal_types", [effect.get("lifesteal_type", "")])
            for target in targets:
                if "倒戈" in types or kind == "mutiny_bonus":
                    self._apply_modifier(api, actor, [target], "weapon_lifesteal", value, duration)
                if "攻心" in types or kind == "lifesteal_bonus":
                    self._apply_modifier(api, actor, [target], "strategy_lifesteal", value, duration)
            return True

        if kind == "strategy_critical_chance_and_damage_bonus":
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            per_buff = _number_at_level_10(effect, "bonus_per_functional_buff", fallback=0.0)
            for target in targets:
                chance = _number_at_level_10(effect, "critical_chance_bonus", fallback=0.0)
                damage = _number_at_level_10(effect, "critical_damage_bonus", fallback=0.0)
                if per_buff:
                    maximum = int(effect.get("max_bonus_stacks", 8) or 8)
                    extra = per_buff * min(maximum, _functional_buff_count(actor))
                    chance += extra
                    damage += extra
                self._apply_modifier(api, actor, [target], "strategy_critical_chance", chance, duration)
                self._apply_modifier(api, actor, [target], "strategy_critical_damage_bonus", damage, duration)
            return True

        if kind in {"command_and_intellect_debuff", "initiative_and_force_debuff", "steal_force_and_command"}:
            pairs = {
                "command_and_intellect_debuff": ("command", "intellect"),
                "initiative_and_force_debuff": ("initiative", "force"),
                "steal_force_and_command": ("force", "command"),
            }[kind]
            targets = self._select_targets(api, actor, target_text, enemy_default=True, context=context)
            for target in targets:
                source_effect = {**effect, "source_target": target.name}
                for stat in pairs:
                    stem = f"{stat}_stolen" if kind == "steal_force_and_command" else "value"
                    value = abs(_calibrated_value(actor, effect, stem, fallback=_fallback_stat_value(self.raw_text)))
                    self._apply_modifier(
                        api, actor, [target], stat, -value, duration, source_effect,
                        notify_attribute_reduction=False,
                    )
                    if kind.startswith("steal"):
                        self._apply_modifier(api, actor, [actor], stat, value, duration, source_effect)
                api.on_attribute_reduced(actor, target, self.name)
            return True

        if kind in {"steal_command_flat", "steal_damage_taken_reduction"}:
            targets = self._select_targets(api, actor, target_text, enemy_default=True, context=context)
            for target in targets:
                source_effect = {**effect, "source_target": target.name}
                if kind == "steal_damage_taken_reduction":
                    value = abs(_calibrated_value(actor, effect, "value", fallback=0.0))
                    self._apply_modifier(api, actor, [target], "damage_taken_reduction_penalty", value, duration, source_effect)
                    self._apply_modifier(api, actor, [actor], "damage_taken_reduction", value, duration, source_effect)
                else:
                    value = abs(_calibrated_value(actor, effect, "value", fallback=_fallback_stat_value(self.raw_text)))
                    self._apply_modifier(
                        api, actor, [target], "command", -value, duration, source_effect,
                        notify_attribute_reduction=False,
                    )
                    recipients = [actor]
                    if effect.get("redistribute_to"):
                        allies = [general for general in api.allies_of(actor).alive_generals if general is not actor]
                        if allies:
                            recipients.append(max(allies, key=lambda general: general.stat("command")))
                    for recipient in recipients:
                        self._apply_modifier(api, actor, [recipient], "command", value / len(recipients), duration, source_effect)
                    api.on_attribute_reduced(actor, target, self.name)
            return True

        if kind == "corresponding_attribute_bonus_flat":
            attribute_states = {
                "武力": ("force", "百战不殆-武"),
                "智力": ("intellect", "百战不殆-智"),
                "统率": ("command", "百战不殆-统"),
            }
            allies = api.allies_of(actor).alive_generals
            if event == "setup":
                for raw_stat in effect.get("attributes", []):
                    configured = attribute_states.get(str(raw_stat))
                    if configured is None or not allies:
                        continue
                    stat, state_name = configured
                    highest = max(allies, key=lambda general: general.stat(stat))
                    self._add_status(api, highest, actor, state_name, None, {"state": state_name})
                    api.log_event(f"{highest.name} 获得【{state_name}】")
                return True
            event_target = context.get("target")
            if not isinstance(event_target, General) or event_target.team != actor.team:
                return True
            value = _number_at_level_10(effect, "value", fallback=_fallback_stat_value(self.raw_text))
            for raw_stat in effect.get("attributes", []):
                configured = attribute_states.get(str(raw_stat))
                if configured is None:
                    continue
                stat, state_name = configured
                if event_target.has_status(state_name):
                    self._apply_modifier(api, actor, [event_target], stat, value, duration, effect)
            return True

        if kind in {"attribute_bonus_from_self", "highest_attribute_bonus_flat", "force_bonus_from_initiative"}:
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            if kind == "attribute_bonus_from_self":
                ratio = _number_at_level_10(effect, "source_attribute_ratio", fallback=0.0)
                for target in targets:
                    for raw_stat in effect.get("attributes", []):
                        stat = STAT_NAME_MAP.get(str(raw_stat), str(raw_stat))
                        self._apply_modifier(api, actor, [target], stat, actor.stat(stat) * ratio, duration, effect)
                return True
            for target in targets:
                if kind == "force_bonus_from_initiative":
                    stat = "force"
                    value = actor.stat("initiative") * _number_at_level_10(effect, "conversion_rate", fallback=0.1)
                else:
                    configured = str(effect.get("stat", ""))
                    stat = STAT_NAME_MAP.get(configured, configured)
                    if not stat:
                        stat = max(STAT_NAME_MAP.values(), key=actor.stat)
                    value = _number_at_level_10(effect, "value", fallback=_fallback_stat_value(self.raw_text))
                self._apply_modifier(api, actor, [target], stat, value, duration, effect)
            return True

        if kind in {"self_and_ally_damage_reduction", "damage_taken_reduction_from_front_row", "damage_taken_reduction_from_back_row"}:
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            for target in targets:
                value = _calibrated_value(actor, effect, "value", fallback=_fallback_modifier_value(self.raw_text, "damage_taken_reduction"))
                self._apply_modifier(api, actor, [target], "damage_taken_reduction", value, duration, effect)
            return True

        if kind == "specific_damage_taken_reduction":
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            damage_kind_stats = {
                "逃兵": "deserter_damage_taken_reduction",
                "传递伤害": "transfer_damage_taken_reduction",
                "传递": "transfer_damage_taken_reduction",
            }
            for target in targets:
                for raw_kind in effect.get("damage_kinds", []):
                    stat = damage_kind_stats.get(str(raw_kind))
                    if stat:
                        value = _calibrated_value(actor, effect, "value", fallback=0.0)
                        self._apply_modifier(api, actor, [target], stat, value, duration, effect)
            return True

        if kind == "same_damage_type_dealt_reduction":
            targets = self._select_targets(api, actor, target_text, enemy_default=True, context=context)
            incoming_kind = context.get("kind")
            if incoming_kind == DamageKind.WEAPON:
                stat = "weapon_damage_dealt_reduction"
            elif incoming_kind == DamageKind.STRATEGY:
                stat = "strategy_damage_dealt_reduction"
            else:
                return True
            for target in targets:
                value = _calibrated_value(actor, effect, "value", fallback=0.0)
                self._apply_modifier(api, actor, [target], stat, value, duration, effect)
            return True

        if kind in {"gain_stack", "stack", "add_state_stack", "gain_stack_at_command_threshold"}:
            state = str(effect.get("state", self.name))
            if effect.get("stacks_min") is not None or effect.get("stacks_max") is not None:
                minimum = int(effect.get("stacks_min", effect.get("stacks_max", 1)) or 1)
                maximum = int(effect.get("stacks_max", minimum) or minimum)
                stacks = api.rng.randint(minimum, maximum)
            else:
                stacks = int(effect.get("stacks", 1) or 1)
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            if effect.get("stacks_per_enemy_outsped") is not None:
                stacks = int(effect["stacks_per_enemy_outsped"]) * sum(
                    actor.stat("initiative") > enemy.stat("initiative")
                    for enemy in api.enemies_of(actor).alive_generals
                )
            if stacks <= 0:
                return True
            for target in targets:
                self._add_status(api, target, actor, state, duration, {**effect, "stacks": stacks})
            return True

        if kind in {"stacking_buff", "temporary_buff"}:
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            state_name = str(effect.get("state", ""))
            for target in targets:
                current = target.status(state_name) if state_name else None
                multiplier = current.stacks if current is not None else 1
                for nested in effect.get("effects", []):
                    if not isinstance(nested, dict):
                        continue
                    nested_kind = str(nested.get("kind", ""))
                    nested_effect = {
                        **nested,
                        "target": target_text,
                        "state": state_name,
                        "condition": str(effect.get("condition", "")),
                        "timing": str(effect.get("timing", "")),
                    }
                    if not state_name:
                        nested_effect["stackable"] = True
                        nested_effect["max_stacks"] = int(effect.get("max_stacks", 1) or 1)
                    if nested_kind == "critical_and_strategy_critical_damage_bonus":
                        value = _number_at_level_10(nested, "value", fallback=0.0) * multiplier
                        self._apply_modifier(api, actor, [target], "critical_damage_bonus", value, duration, nested_effect)
                        self._apply_modifier(api, actor, [target], "strategy_critical_damage_bonus", value, duration, nested_effect)
                        continue
                    stat = _modifier_stat_from_kind(nested_kind)
                    if not stat:
                        raise ValueError(f"战法 {self.name} 的嵌套效果存在未实现类型: {nested_kind}")
                    value = _number_at_level_10(nested, "value", fallback=0.0) * multiplier
                    if nested_kind in NEGATIVE_MODIFIER_KINDS:
                        value = -abs(value)
                    self._apply_modifier(api, actor, [target], stat, value, duration, nested_effect)
            return True

        if kind == "stacking_stat_bonus":
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            stat = STAT_NAME_MAP.get(str(effect.get("stat", "")), str(effect.get("stat", "force")))
            nested_effect = {**effect, "stackable": True}
            self._apply_modifier(
                api,
                actor,
                targets,
                stat,
                _number_at_level_10(effect, "value", fallback=0.0),
                duration,
                nested_effect,
            )
            return True

        if kind == "stacking_damage_rate_bonus":
            state = f"{self.name}-本回合伤害系数"
            targets = [actor]
            for target in targets:
                self._add_status(
                    api,
                    target,
                    actor,
                    state,
                    1,
                    {**effect, "state": state, "stacks": 1, "max_stacks": int(effect.get("max_stacks", 1) or 1)},
                )
            return True

        if kind == "per_stack_damage_and_crit_bonus":
            return True

        if kind in {"apply_random_control_state", "apply_random_state", "apply_random_unique_state", "extra_apply_random_unique_state"}:
            states = list(effect.get("states", []))
            if effect.get("state_group") == "布阵状态":
                states = LAYOUT_STATES.copy()
            elif effect.get("state_category") == "异常状态":
                states = ABNORMAL_STATUSES.copy()
            if not states:
                states = CONTROL_STATUSES if kind == "apply_random_control_state" else ["焚烧", "中毒", "畏惧", "技穷", "缴械", "虚弱", "断粮"]
            targets = self._select_targets(api, actor, target_text, enemy_default="敌军" in target_text, context=context)
            state_count = max(1, int(effect.get("state_count", 1) or 1))
            for target in targets:
                if not _roll_effect_for_target(api, effect, actor=actor):
                    continue
                prefer_unheld = bool(
                    effect.get("prefer_unheld_state")
                    or effect.get("prefer_different_state")
                    or kind in {"apply_random_unique_state", "extra_apply_random_unique_state"}
                )
                available = ([state for state in states if not target.has_status(state)] or states) if prefer_unheld else states
                for state in api.rng.sample(available, min(state_count, len(available))):
                    if state in LAYOUT_STATES:
                        self._grant_layout_state(api, actor, target, state, duration, effect)
                    else:
                        self._add_status(api, target, actor, state, duration, effect)
                        self._apply_named_state_modifier(api, actor, target, state, duration, effect)
                    api.log_event(f"{target.name} 获得 {state}")
            return True

        if kind in {"cannot_active_skill", "cannot_basic_attack"}:
            status = "技穷" if kind == "cannot_active_skill" else "缴械"
            for target in self._select_targets(api, actor, target_text, enemy_default=False, context=context):
                self._add_status(api, target, actor, status, 1, effect)
            return True

        if kind in {"cleanse", "dispel_negative_state", "clear_state_stacks"}:
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            if kind == "clear_state_stacks":
                state = str(effect.get("state", ""))
                for target in targets:
                    self._clear_state_effects(target, state)
            else:
                count = int(effect.get("cleanse_negative_states", effect.get("count", 1)) or 1)
                for target in targets:
                    _cleanse_negative_states(target, count)
            return True

        if kind == "consume_state_and_grant_state":
            for target in self._select_targets(api, actor, target_text, enemy_default=False, context=context):
                consumed = target.consume_status_stack(
                    str(effect.get("consume_state", "")),
                    int(effect.get("consume_stacks", 1) or 1),
                )
                if not consumed:
                    continue
                grant = str(effect.get("grant_state", ""))
                if grant:
                    self._add_status(
                        api,
                        target,
                        actor,
                        grant,
                        duration,
                        {"kind": "gain_stack", "stacks": int(effect.get("grant_stacks", 1) or 1)},
                    )
            return True

        if kind in {"basic_attack", "extra_basic_attack", "mutual_basic_attack", "consume_stacks_for_extra_basic_attacks"}:
            times = int(effect.get("times", 1) or 1)
            if kind == "consume_stacks_for_extra_basic_attacks":
                state = actor.status(str(effect.get("state", "")))
                times = min(int(effect.get("max_stacks", 10) or 10), state.stacks if state else 0)
                if state:
                    actor.consume_status_stack(state.name, times)
            targets = self._select_targets(api, actor, target_text, enemy_default=True, context=context)
            self_immune_states = set(effect.get("self_immune_states_during_exchange", []))
            for index in range(times):
                target = targets[index % len(targets)] if targets else None
                api.perform_basic_attack(
                    actor,
                    target,
                    ignore_disarm=bool(
                        effect.get("ignore_state") == "缴械"
                        or effect.get("ignore_states")
                        or "缴械" in self_immune_states
                    ),
                )
            if kind == "mutual_basic_attack":
                for target in targets:
                    api.perform_basic_attack(target, actor)
            return True

        if kind == "multi_hit":
            hits = api.rng.randint(int(effect.get("hit_count_min", 1)), int(effect.get("hit_count_max", 1)))
            kinds = effect.get("damage_kinds", ["兵刃"])
            for _ in range(hits):
                context["_force_reselect"] = True
                targets = self._select_targets(api, actor, target_text, enemy_default=True, context=context)
                if not targets:
                    break
                for target in targets:
                    for raw_kind in kinds:
                        if not actor.is_alive or not target.is_alive:
                            break
                        damage_kind = DamageKind.STRATEGY if "谋略" in str(raw_kind) else DamageKind.WEAPON
                        power = _number_at_level_10(effect, "damage_rate", fallback=self.power)
                        round_bonus = actor.status(f"{self.name}-本回合伤害系数")
                        if round_bonus is not None:
                            power += _number_at_level_10(round_bonus.payload, "value", fallback=0.0) * round_bonus.stacks
                        api.deal_damage(actor, target, power, damage_kind, self.name)
                if "讨伐" in self.raw_text:
                    marker = actor.status(f"{self.name}-讨伐次数")
                    before = marker.stacks if marker is not None else 0
                    self._add_status(api, actor, actor, f"{self.name}-讨伐次数", None, {"stacks": 1, "stackable": True})
                    if (before + 1) % 3 == 0:
                        deserter_effect = next(
                            (item for item in self.data_effects if item.get("kind") == "apply_state" and item.get("state") == "逃兵"),
                            None,
                        )
                        enemies = api.enemies_of(actor).alive_generals
                        if enemies and deserter_effect is not None:
                            target = min(enemies, key=lambda general: general.troops / max(1, general.max_troops))
                            amount = self._deserter_amount(actor, target, deserter_effect)
                            if amount is not None:
                                api.settle_deserters(actor, target, amount, self.name)
            context.pop("_force_reselect", None)
            return True

        if kind in {"deserter_damage", "transfer_damage", "splash_damage_from_basic_attack", "friendly_weapon_damage"}:
            if kind == "deserter_damage":
                power = actor.troops * float(effect.get("current_troop_ratio", 0.1))
                api.settle_deserters(actor, actor, int(power), self.name)
                return True
            if kind == "transfer_damage":
                power = float(context.get("damage", 0)) * _number_at_level_10(effect, "damage_rate", fallback=0.5)
                damage_kind = DamageKind.TRANSFER
            else:
                power = _number_at_level_10(effect, "damage_rate", fallback=self.power)
                damage_kind = DamageKind.WEAPON
            damage_actor = self._select_damage_source(api, actor, effect)
            if kind == "transfer_damage" and isinstance(context.get("attacker"), General):
                damage_actor = context["attacker"]
            targets = self._select_targets(api, actor, target_text, enemy_default=kind != "friendly_weapon_damage", context=context)
            for target in targets:
                api.deal_damage(damage_actor, target, power, damage_kind, self.name, effect_owner=actor)
            return True

        if kind in {"damage_to_heal", "double_heal"}:
            portion = float(effect.get("heal_portion_of_damage", effect.get("heal_from_damage_rate_at_level_10", 0.4)) or 0.4)
            base_amount = float(context.get("damage", 0)) * portion
            if kind == "double_heal":
                base_amount = float(context.get("healing", 0))
            targets = self._select_targets(api, actor, str(effect.get("heal_target", target_text or "我军兵力最低单体")), enemy_default=False, context=context)
            for target in targets:
                api.heal_fixed(actor, target, int(base_amount), self.name, is_extra=True)
            return True

        if kind == "force_critical_and_heal_lowest_ally":
            target = context.get("target")
            if event != "before_damage_dealt" or not isinstance(target, General):
                return True
            context["force_critical"] = True
            context.setdefault("post_damage_heals", []).append(
                {
                    "actor": actor,
                    "source": self.name,
                    "portion": _calibrated_value(
                        actor,
                        effect,
                        "heal_from_damage_rate",
                        fallback=float(effect.get("heal_from_damage_rate_at_level_10", 0.25) or 0.25),
                    ),
                }
            )
            return True

        if kind == "cover_damage":
            target = context.get("target")
            incoming = int(context.get("incoming_damage", 0) or 0)
            if event != "before_damage_taken" or not isinstance(target, General) or target is actor:
                if not (target is actor and "放权目标" in target_text):
                    return True
            requires_large_hit = "高于当前兵力10%" in (
                str(effect.get("condition", "")) + str(effect.get("timing", ""))
            )
            if (
                target.team != actor.team
                or (requires_large_hit and incoming <= target.troops * 0.10)
                or context.get("redirect_target") is not None
            ):
                return True
            limit = int(effect.get("max_triggers_per_ally_per_round", 0) or 0) or None
            if not api.consume_trigger(actor, self.name, f"cover:{target.name}", limit):
                return True
            redirect = actor
            if "放权目标" in target_text:
                holders = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
                redirect = next((holder for holder in holders if holder is not target), actor)
            if redirect is target:
                return True
            context["redirect_target"] = redirect
            api.log_event(f"{actor.name} 的【{self.name}】令 {redirect.name} 为 {target.name} 承担本次伤害")
            return True

        if kind == "redirect_damage_to_guard":
            target = context.get("target")
            if event != "before_damage_taken" or target is not actor or context.get("redirect_target") is not None:
                return True
            guard_state = str(effect.get("guard_state", "协防"))
            guard = next(
                (
                    candidate
                    for candidate in api.allies_of(actor).alive_generals
                    if candidate is not actor and candidate.has_status(guard_state)
                ),
                None,
            )
            if guard is None:
                return True
            context["redirect_target"] = guard
            context.setdefault("current_damage_reductions", []).append(
                _number_at_level_10(effect, "damage_reduction", fallback=0.0)
            )
            api.log_event(f"{guard.name} 的{guard_state}为 {actor.name} 承担本次伤害")
            return True

        if kind == "trigger_state" and str(effect.get("state", "")) == "不屈":
            target = context.get("target")
            incoming = int(context.get("incoming_damage", 0) or 0)
            allies_alive = [candidate for candidate in api.allies_of(actor).alive_generals if candidate is not actor]
            if event != "before_damage_taken" or target is not actor or incoming < actor.troops or not allies_alive:
                return True
            marker = actor.status("不屈已触发")
            used = marker.stacks if marker is not None else 0
            chance = max(
                0.0,
                _number_at_level_10(effect, "trigger_chance", fallback=1.0)
                - used * _number_at_level_10(effect, "next_trigger_chance_reduction", fallback=0.1),
            )
            if used > 0 and api.rng.random() >= chance:
                return True
            context["prevent_fatal"] = True
            self._add_status(api, actor, actor, "不屈已触发", None, {"stacks": 1, "stackable": True})
            api.log_event(f"{actor.name} 触发不屈，免疫本次致命伤害")
            return True

        if kind == "transfer_troops":
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            if targets:
                amount = min(actor.troops - 1, int(actor.troops * _number_at_level_10(effect, "value", fallback=0.4)))
                if amount > 0:
                    actor.troops -= amount
                    targets[0].troops = min(targets[0].healable_max_troops(), targets[0].troops + amount)
            return True

        if kind in {"cast_again", "extra_active_skill_cast", "reroll_active_skill"}:
            source_skill = context.get("skill")
            skill_name = str(effect.get("skill", getattr(source_skill, "name", self.name)))
            if kind == "reroll_active_skill":
                failed_actor = context.get("actor")
                if not isinstance(failed_actor, General):
                    return True
                cost_state = str(effect.get("cost_state", ""))
                cost = int(effect.get("cost_stacks", 1) or 1)
                state = actor.status(cost_state) if cost_state else None
                if cost_state and (state is None or state.stacks < cost):
                    return True
                if cost_state:
                    actor.consume_status_stack(cost_state, cost)
                    api.log_event(f"{actor.name} 消耗 {cost} 层{cost_state}，令 {failed_actor.name} 的{skill_name}重新判定")
                api.cast_skill(failed_actor, skill_name)
                return True
            if effect.get("cannot_trigger_again") and context.get("extra_cast_chain"):
                return True
            api.force_cast_skill(actor, skill_name, {"extra_cast_chain": True})
            return True

        if kind == "next_prepare_skill_skip_preparation_rounds":
            self._add_status(api, actor, actor, "下次准备战法跳过准备", duration, {"skip_rounds": int(effect.get("skip_rounds", 1) or 1)})
            return True

        if kind == "next_damage_guaranteed_critical_or_strategy_critical":
            bonus = _number_at_level_10(effect, "critical_or_strategy_critical_damage_bonus", fallback=0.0)
            for target in self._select_targets(api, actor, target_text, enemy_default=False, context=context):
                self._add_status(api, target, actor, "下次伤害必定会心或奇谋", duration, {"critical_damage_bonus": bonus})
            return True

        if kind == "target_priority":
            return True

        if kind == "trigger_named_effect":
            name = str(effect.get("effect_name", self.name))
            payload = dict(context)
            payload.setdefault("actor", actor)
            api.trigger_named_event(actor, name, payload)
            return True

        if kind == "random_effect_bundle":
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            choices = [choice for choice in effect.get("effects", []) if isinstance(choice, dict)]
            minimum = max(1, int(effect.get("effect_count_min", 1) or 1))
            maximum = max(minimum, int(effect.get("effect_count_max", minimum) or minimum))
            for target in targets:
                if not choices:
                    continue
                count = min(len(choices), api.rng.randint(minimum, maximum))
                for choice in api.rng.sample(choices, count):
                    choice_kind = str(choice.get("kind", ""))
                    choice_duration = _duration(choice, self.raw_text, duration or 1)
                    if choice_kind == "heal":
                        power = _number_at_level_10(choice, "heal_rate", fallback=self._fallback_heal_power())
                        api.heal(actor, target, power, self.name)
                    elif choice_kind == "state_immunity":
                        state = str(choice.get("state", ""))
                        if state:
                            self._add_status(api, target, actor, f"{state}免疫", choice_duration, choice)
                            api.log_event(f"{target.name} 获得 {state}免疫")
                    else:
                        stat = _modifier_stat_from_kind(choice_kind)
                        if not stat:
                            raise ValueError(f"战法 {self.name} 的随机效果包存在未实现效果类型: {choice_kind}")
                        value = _number_at_level_10(choice, "value", fallback=0.0)
                        self._apply_modifier(api, actor, [target], stat, value, choice_duration, choice)
            return True

        if kind == "formation_bonus":
            team = api.allies_of(actor)
            bonus = _number_at_level_10(effect, "value", fallback=0.0)
            for target in team.alive_generals:
                formation_modifiers = [
                    modifier
                    for modifier in target.modifiers
                    if modifier.name == team.formation_name and modifier.source_skill is None
                ]
                for modifier in formation_modifiers:
                    self._apply_modifier(
                        api,
                        actor,
                        [target],
                        modifier.stat,
                        modifier.value * bonus,
                        duration=None,
                        effect=effect,
                    )
            return True

        if kind == "board_state_bonus":
            team = api.allies_of(actor)
            front_count = sum(general.position == "front" for general in team.generals)
            if event == "setup":
                state = f"棋局增益-{front_count}前排"
                self._add_status(api, actor, actor, state, None, effect)
                if front_count == 1:
                    for target in team.alive_generals:
                        weight = 0.85 if target.position == "front" else 0.075
                        self._apply_modifier(api, actor, [target], "basic_target_weight_override", weight, None, effect)
                        if target.position == "front":
                            self._apply_modifier(api, actor, [target], "damage_taken_reduction", 0.12, None, effect)
                elif front_count == 2 and team.alive_generals:
                    target = min(team.alive_generals, key=lambda general: general.stat("command"))
                    self._apply_modifier(api, actor, [target], "damage_against_front_bonus", 0.20, None, effect)
                return True

            subject = context.get("actor")
            if front_count == 2 and event == "action_start" and isinstance(subject, General) and subject.team == actor.team:
                alive = team.alive_generals
                if alive and subject is min(alive, key=lambda general: general.stat("command")):
                    damage_kind = DamageKind.WEAPON if subject.stat("force") >= subject.stat("intellect") else DamageKind.STRATEGY
                    for target in self._select_targets(api, subject, "敌军随机1-2人", True, context):
                        api.deal_damage(subject, target, 1.60, damage_kind, self.name, effect_owner=actor)
                return True
            if front_count == 3 and event == "round_end" and team.alive_generals:
                source = max(team.alive_generals, key=lambda general: general.stat("intellect"))
                for target in api.enemies_of(actor).alive_generals:
                    api.deal_damage(source, target, 0.60, DamageKind.STRATEGY, self.name, effect_owner=actor)
                return True
            return True

        if kind == "settle_state_damage":
            state_name = str(effect.get("state", ""))
            trigger_state = actor.status("狂骨") if state_name == "流血" else None
            if trigger_state is not None and trigger_state.stacks not in {9, 15}:
                return True
            marker_name = f"{self.name}-{state_name}已结算{trigger_state.stacks}" if trigger_state is not None else ""
            if marker_name and actor.has_status(marker_name):
                return True
            if trigger_state is not None and not api.consume_trigger(actor, self.name, f"settle:{trigger_state.stacks}", 1):
                return True
            if marker_name:
                actor.statuses.append(
                    StatusEffect(
                        marker_name,
                        remaining_rounds=None,
                        source_actor=actor.name,
                        source_team=actor.team,
                        payload={"source_skill": self.name, "internal": True},
                    )
                )
            generals = [general for general in context.get("all_generals", []) if isinstance(general, General)]
            if not generals:
                generals = api.allies_of(actor).alive_generals + api.enemies_of(actor).alive_generals
            for target in generals:
                state = target.status(state_name)
                if state is None or not target.is_alive:
                    continue
                source = next((general for general in generals if general.name == state.source_actor), actor)
                damage_kind = DamageKind.WEAPON if state_name == "流血" else DamageKind.STRATEGY
                power = float(state.payload.get("power", 0.60)) * max(1, state.stacks)
                api.deal_damage(source, target, power, damage_kind, state_name)
                if effect.get("clear_state"):
                    target.statuses = [candidate for candidate in target.statuses if candidate is not state]
            return True

        if kind in {"trigger_state", "skill_damage_rate_increase_per_round"}:
            state = str(effect.get("state", effect.get("effect_name", kind)))
            targets = self._select_targets(api, actor, target_text, enemy_default=False, context=context)
            for target in targets or [actor]:
                self._add_status(api, target, actor, state, duration, effect)
            return True

        return False

    def _apply_text_modifiers(self, api: BattleApi, actor: General) -> bool:
        raw = self.raw_text
        rules = [
            ("普通攻击伤害提升", "basic_damage_bonus", False),
            ("主动战法发动率", "active_chance_bonus", False),
            ("发动率", f"{self.timing.value}_chance_bonus", False),
            ("造成伤害提升", "damage_dealt_bonus", False),
            ("看破提升", "insight", False),
            ("造成伤害降低", "damage_dealt_reduction", True),
            ("兵刃伤害提升", "weapon_damage_bonus", False),
            ("谋略伤害提升", "strategy_damage_bonus", False),
            ("受到伤害降低", "damage_taken_reduction", False),
            ("受到伤害提升", "damage_taken_increase", True),
            ("规避率", "evasion_chance", False),
            ("会心几率", "critical_chance", False),
            ("奇谋几率", "critical_chance", False),
            ("反击率", "counter_chance", False),
            ("反击伤害", "counter_damage_bonus", False),
        ]
        did_anything = False
        for marker, stat, enemy_default in rules:
            if marker not in raw:
                continue
            value = _fallback_modifier_value(raw, stat)
            if value == 0:
                continue
            targets = [actor] if "自身" in raw[: raw.find(marker) + len(marker)] else self._default_modifier_targets(api, actor, enemy_default)
            self._apply_modifier(api, actor, targets, stat, value, duration=self.duration)
            did_anything = True

        for cn_name, stat in STAT_NAME_MAP.items():
            if cn_name not in raw or ("提升" not in raw and "降低" not in raw):
                continue
            value = _fallback_stat_value(raw)
            if value == 0:
                continue
            if "降低" in raw:
                value = -abs(value)
            targets = self._default_modifier_targets(api, actor, value < 0)
            self._apply_modifier(api, actor, targets, stat, value, duration=self.duration)
            did_anything = True
        return did_anything

    def _apply_text_statuses(self, api: BattleApi, actor: General) -> bool:
        raw = self.raw_text
        duration = _duration({}, raw, self.duration)
        if "随机获得1种控制状态" in raw:
            for target in api.pick_damage_targets(actor, self._target_count(raw)):
                status = api.rng.choice(CONTROL_STATUSES)
                self._add_status(api, target, actor, status, duration)
                self._apply_named_state_modifier(api, actor, target, status, duration)
                api.log_event(f"{target.name} 获得 {status}")
            return True

        did_anything = False
        for status_name in KNOWN_STATUSES:
            if not _text_applies_status(raw, status_name):
                continue
            enemy_default = _is_harmful_state(status_name)
            for target in self._select_targets(api, actor, raw, enemy_default=enemy_default):
                self._add_status(api, target, actor, status_name, duration)
                self._apply_named_state_modifier(api, actor, target, status_name, duration)
                api.log_event(f"{target.name} 获得 {status_name}")
                did_anything = True
        return did_anything

    def _select_targets(
        self,
        api: BattleApi,
        actor: General,
        target_text: str,
        enemy_default: bool,
        context: dict[str, Any] | None = None,
    ) -> list[General]:
        context = context or {}
        target_text = target_text or self.raw_text
        override = context.get("_target_override")
        if isinstance(override, General) and target_text in context.get("_target_override_texts", ()):
            if target_text == "敌军目标" and override.team == actor.team:
                return []
            if target_text == "友军目标" and override.team != actor.team:
                return []
            return [override] if override.is_alive else []
        count = self._selection_count(api, target_text)
        cache_key = (target_text, bool(context.get("prefer_back")), bool(context.get("prefer_front")))
        target_cache = context.setdefault("_target_cache", {})
        if not context.get("_force_reselect") and cache_key in target_cache:
            return [target for target in target_cache[cache_key] if target.is_alive]

        def remember(targets: list[General]) -> list[General]:
            if not context.get("_force_reselect"):
                target_cache[cache_key] = targets
            return targets
        event_target = context.get("target")
        event_actor = context.get("actor")
        last_targets = [target for target in context.get("last_targets", []) if isinstance(target, General) and target.is_alive]
        # Reactive effects must use the target carried by the event itself.
        # Reusing last_targets here can turn an enemy-targeted trigger into a
        # self/ally hit after a previous effect selected a friendly unit.
        if isinstance(event_target, General) and target_text in {
            "目标", "当前目标", "普通攻击目标", "伤害目标", "攻击目标",
            "属性降低目标", "追伤目标", "本次伤害", "该次伤害",
        }:
            return remember([event_target]) if event_target.is_alive else []
        if "该目标两名队友" in target_text and isinstance(event_target, General):
            candidates = [
                general for general in api.allies_of(event_target).alive_generals
                if general is not event_target
            ]
            return remember(api.pick_targets(Team(event_target.team, candidates), count))
        if "目标友军" in target_text and last_targets:
            reference = last_targets[0]
            context["_condition_reference"] = reference
            candidates = [
                general for general in api.allies_of(reference).alive_generals
                if general is not reference
            ]
            return remember(api.pick_targets(Team(reference.team, candidates), count))
        if target_text in {"敌军目标", "友军目标"} and last_targets:
            enemy_team = api.enemies_of(actor).name
            desired_team = enemy_team if target_text == "敌军目标" else actor.team
            return remember([target for target in last_targets if target.team == desired_team])
        if target_text == "目标" and last_targets:
            return remember(last_targets)
        if "伤害来源" in target_text and isinstance(context.get("attacker"), General):
            return remember([context["attacker"]])
        if "受伤目标" in target_text and isinstance(event_target, General):
            return remember([event_target])
        if any(marker in target_text for marker in ("伤害目标", "攻击目标", "目标", "本次伤害")) and isinstance(event_target, General):
            if target_text in {
                "目标", "当前目标", "普通攻击目标", "伤害目标", "攻击目标", "治疗目标",
                "属性降低目标", "追伤目标", "本次伤害", "该次伤害",
            }:
                return remember([event_target])
        if "放权目标" in target_text:
            holders = [
                general
                for general in api.allies_of(actor).alive_generals
                if any(
                    status.name == "放权" and (status.source_actor == actor.name or status.source_actor is None)
                    for status in general.statuses
                )
            ]
            if holders:
                return remember(holders[:count])
        if any(marker in target_text for marker in ("获得者", "状态持有者", "持有者")) and isinstance(event_target, General):
            return remember([event_target])
        if "造成伤害的队友" in target_text and isinstance(context.get("attacker"), General):
            return remember([context["attacker"]])
        if any(marker in target_text for marker in ("施策目标", "协防队友")):
            subject = context.get("attacker") or context.get("actor")
            if isinstance(subject, General):
                return remember([subject])
        if any(marker in target_text for marker in (
            "行动武将", "行动者", "抵御消耗者",
        )) and isinstance(event_actor, General):
            return remember([event_actor])
        if "对应敌军" in target_text:
            return remember([
                enemy for enemy in api.enemies_of(actor).alive_generals
                if actor.stat("initiative") > enemy.stat("initiative")
            ])
        holder_match = re.search(r"持有([^，、的]+)的武将", target_text)
        if holder_match:
            state_name = holder_match.group(1).removesuffix("状态")
            return remember([
                general for general in api.allies_of(actor).alive_generals
                if general.has_status(state_name)
            ])
        if any(marker in target_text for marker in ("自身及随机友军单体", "自身及随机一名队友", "自身和随机一名队友", "自身与随机一名队友", "自身和随机友军单体", "自身与随机友军单体")):
            targets = [actor]
            targets.extend(api.pick_targets(api.allies_of(actor), 1, exclude=actor))
            return remember(targets)
        if "自身" in target_text and ("友军" in target_text or "队友" in target_text) and any(marker in target_text for marker in ("和", "与", "及")):
            allies = [general for general in api.allies_of(actor).alive_generals if general is not actor]
            if "兵力最低" in target_text:
                picked = sorted(allies, key=lambda general: general.troops / max(1, general.max_troops))[:1]
            else:
                picked = api.pick_targets(Team(api.allies_of(actor).name, allies), 1)
            return remember([actor, *picked])
        if (
            "自身" in target_text
            and "除自身外" not in target_text
            and "敌我全体" not in target_text
            and "敌军" not in target_text
            and "我军全体" not in target_text
            and "友军" not in target_text
        ):
            return remember([actor])

        if "敌我全体" in target_text or "除自身外" in target_text:
            candidates = [
                general
                for general in api.allies_of(actor).alive_generals + api.enemies_of(actor).alive_generals
                if general is not actor
            ]
            return remember(candidates if "全体" in target_text and "随机" not in target_text else api.pick_targets(Team("敌我", candidates), count))

        hostile_selection = enemy_default or "敌军" in target_text
        if actor.has_status("混乱") and not actor.has_status("清醒") and self.timing in {SkillTiming.ACTIVE, SkillTiming.PURSUIT} and hostile_selection:
            candidates = [
                general
                for general in api.allies_of(actor).alive_generals + api.enemies_of(actor).alive_generals
                if general is not actor
            ]
            return remember(api.pick_targets(Team("混乱目标", candidates), count))

        team = api.enemies_of(actor) if ("敌军" in target_text or enemy_default) else api.allies_of(actor)
        for troop_type in ("盾兵", "弓兵", "枪兵", "骑兵"):
            if troop_type in target_text:
                candidates = [general for general in team.alive_generals if general.troop_type == troop_type]
                return remember(candidates if "随机" not in target_text else api.pick_targets(Team(team.name, candidates), count))
        if "持有异常状态" in target_text:
            candidates = [
                general for general in team.alive_generals
                if any(general.has_status(state) for state in ABNORMAL_STATUSES)
            ]
            return remember(candidates if "随机" not in target_text else api.pick_targets(Team(team.name, candidates), count))
        state_match = re.search(r"持有([^，、的]+)(?:状态)?的敌军", target_text)
        if state_match:
            state_name = state_match.group(1).removesuffix("状态")
            candidates = [general for general in team.alive_generals if general.has_status(state_name)]
            return remember(candidates if "随机" not in target_text else api.pick_targets(Team(team.name, candidates), count))
        if context.get("prefer_back"):
            back = [general for general in team.alive_generals if general.position == "back"]
            if back:
                return remember(api.pick_targets(Team(team.name, back), count))
        if context.get("prefer_front"):
            front = [general for general in team.alive_generals if general.position == "front"]
            if front:
                return remember(api.pick_targets(Team(team.name, front), count))
        if "全体" in target_text and "随机" not in target_text:
            return remember(team.alive_generals)
        if "兵力最低" in target_text:
            return remember(sorted(team.alive_generals, key=lambda general: general.troops / general.max_troops)[:count])
        for cn_name, stat in (("武力", "force"), ("智力", "intellect"), ("统率", "command"), ("先攻", "initiative")):
            if cn_name not in target_text:
                continue
            reverse = "最高" in target_text or "最大" in target_text
            return remember(sorted(team.alive_generals, key=lambda general: general.stat(stat), reverse=reverse)[:count])
        if "前排" in target_text:
            front = [general for general in team.alive_generals if general.position == "front"]
            if front:
                return remember(api.pick_targets(Team(team.name, front), count))
        if "后排" in target_text:
            back = [general for general in team.alive_generals if general.position == "back"]
            if back:
                return remember(api.pick_targets(Team(team.name, back), count))
        exclude_actor = actor if ("友军" in target_text or "队友" in target_text) and "自身" not in target_text else None
        return remember(api.pick_targets(team, count, exclude=exclude_actor))

    def _selection_count(self, api: BattleApi, text: str) -> int:
        match = re.search(r"随机\s*(\d+)\s*[-~～至到]\s*(\d+)\s*(?:人|名|个|次)?", text)
        if match:
            minimum, maximum = int(match.group(1)), int(match.group(2))
            return api.rng.randint(min(minimum, maximum), max(minimum, maximum))
        return self._target_count(text)

    def _default_modifier_targets(self, api: BattleApi, actor: General, enemy_default: bool) -> list[General]:
        if "敌军全体" in self.raw_text:
            return api.enemies_of(actor).alive_generals
        if "我军全体" in self.raw_text:
            return api.allies_of(actor).alive_generals
        if "自身" in self.raw_text:
            return [actor]
        team = api.enemies_of(actor) if enemy_default else api.allies_of(actor)
        return api.pick_targets(team, self._target_count(self.raw_text))

    def _select_damage_source(self, api: BattleApi, actor: General, effect: dict[str, Any]) -> General:
        selector = str(effect.get("source_selector", effect.get("source", "")))
        if not selector or selector in {"自身", "该次普通攻击"}:
            return actor
        candidates = api.allies_of(actor).alive_generals
        if "玉玺持有者" in selector:
            holder = next((candidate for candidate in candidates if candidate.has_status("玉玺")), None)
            return holder or actor
        if "友军" in selector:
            candidates = [candidate for candidate in candidates if candidate is not actor]
        for label, stat in (("武力", "force"), ("智力", "intellect"), ("统率", "command"), ("先攻", "initiative")):
            if label in selector and candidates:
                return max(candidates, key=lambda candidate: candidate.stat(stat))
        named = next((candidate for candidate in candidates if candidate.name in selector), None)
        return named or actor

    def _damage_power_for_target(
        self,
        effect: dict[str, Any],
        target: General,
        base_power: float,
        preexisting_statuses: dict[int, set[str]],
    ) -> float:
        power = base_power
        statuses = preexisting_statuses.get(id(target), set())
        required_state = str(effect.get("damage_rate_bonus_if_target_has_state", ""))
        if required_state and required_state in statuses:
            power += float(effect.get("damage_rate_bonus", 0.0) or 0.0)
        category = str(effect.get("damage_rate_bonus_if_target_has_state_category", ""))
        if category == "属性降低状态" and any(
            modifier.value < 0 and modifier.stat in STAT_NAME_MAP.values() for modifier in target.modifiers
        ):
            power += float(effect.get("damage_rate_bonus", 0.0) or 0.0)
        abnormal_count = sum(state in statuses for state in ABNORMAL_STATUSES)
        maximum = int(effect.get("max_bonus_count", abnormal_count) or abnormal_count)
        power += float(effect.get("damage_rate_bonus_per_target_abnormal_state", 0.0) or 0.0) * min(abnormal_count, maximum)
        if effect.get("bonus_per_chizhi_stack_at_level_10") is not None:
            chizhi = target.status("迟滞")
            power += _number_at_level_10(effect, "bonus_per_chizhi_stack", fallback=0.0) * (chizhi.stacks if chizhi else 0)
        extra_per_stack = float(effect.get("additional_damage_per_state_stack", 0.0) or 0.0)
        if extra_per_stack:
            state = target.status(str(effect.get("state", "")))
            power += extra_per_stack * (state.stacks if state else 0)
        return max(0.0, power)

    def _damage_context_for_target(
        self,
        api: BattleApi,
        effect: dict[str, Any],
        target: General,
        preexisting_statuses: dict[int, set[str]],
    ) -> dict[str, Any]:
        statuses = preexisting_statuses.get(id(target), set())
        multiplier = 1.0
        state_for_value = str(effect.get("damage_value_bonus_if_target_has_state", ""))
        if state_for_value and state_for_value in statuses:
            multiplier *= 1.0 + float(effect.get("damage_value_bonus", 0.0) or 0.0)
        state_for_damage = str(effect.get("damage_bonus_if_target_has_state", ""))
        if state_for_damage and state_for_damage in statuses:
            multiplier *= 1.0 + float(effect.get("damage_bonus", 0.0) or 0.0)
        if effect.get("damage_value_bonus_if_target_has_negative_state") is not None:
            has_negative = any(_is_harmful_state(state) for state in statuses) or any(
                modifier.value < 0 for modifier in target.modifiers
            )
            if has_negative:
                multiplier *= 1.0 + float(effect["damage_value_bonus_if_target_has_negative_state"])
        extra_chance = _number_at_level_10(effect, "extra_damage_value_bonus_chance", fallback=0.0)
        if extra_chance > 0 and api.rng.random() < min(1.0, extra_chance):
            multiplier *= 1.0 + float(effect.get("extra_damage_value_bonus", 0.0) or 0.0)
        if str(effect.get("kind", "")) == "follow_up_weapon_damage" and any(
            _is_harmful_state(state) for state in statuses
        ):
            sibling = next(
                (item for item in self.data_effects if item.get("kind") == "follow_up_damage_bonus"),
                None,
            )
            if sibling is not None:
                multiplier *= 1.0 + _number_at_level_10(sibling, "value", fallback=0.0)
        ignore_stat = str(effect.get("ignore_stat", ""))
        return {
            "cannot_critical": bool(effect.get("cannot_trigger_critical", False)),
            "ignore_damage_reduction": _number_at_level_10(effect, "ignore_damage_reduction", fallback=0.0),
            "current_damage_multiplier": multiplier,
            "ignore_target_command": "统率" in ignore_stat,
            "ignore_target_intellect": "智力" in ignore_stat,
            "critical_chance_bonus": float(effect.get("critical_chance_bonus_during_cast", 0.0) or 0.0),
        }

    def _deserter_amount(self, actor: General, target: General, effect: dict[str, Any]) -> int | None:
        if effect.get("implementation_status") == "pending_fit":
            return None

        formula = effect.get("deserter_formula")
        if isinstance(formula, dict):
            amount = int(
                actor.stat("force") * float(formula.get("force_coefficient", 0.0))
                + actor.stat("intellect") * float(formula.get("intellect_coefficient", 0.0))
                + float(formula.get("constant", 0.0))
            )
        elif "current_troop_ratio" in effect:
            amount = int(target.troops * float(effect["current_troop_ratio"]))
        else:
            amount = int(effect.get("base_amount", 300) or 300)
        if "max_damage" in effect:
            amount = min(amount, int(effect["max_damage"]))
        return max(1, min(target.troops, amount))

    def _apply_modifier(
        self,
        api: BattleApi,
        actor: General,
        targets: list[General],
        stat: str,
        value: float,
        duration: int | None = None,
        effect: dict[str, Any] | None = None,
        notify_attribute_reduction: bool = True,
    ) -> None:
        expires_after_turn = _modifier_expiry(self, api.round_no, duration, effect)
        effect_identity = self.name
        if effect:
            identity_parts = [
                str(effect.get(key, ""))
                for key in ("kind", "target", "state", "condition", "timing", "source_target")
            ]
            effect_identity = f"{self.name}:" + ":".join(identity_parts)
        stackable = bool(
            (effect or {}).get("stackable")
            or (effect or {}).get("max_stacks")
            or "stacking" in str((effect or {}).get("kind", ""))
        )
        max_stacks = int((effect or {}).get("max_stacks", 0) or 0) or None
        for target in targets:
            changed_stat = stat.removesuffix("_percent_bonus")
            tracks_official_attribute = changed_stat in OFFICIAL_ATTRIBUTE_STATS
            previous_attribute_value = target.stat(changed_stat) if tracks_official_attribute else 0.0
            reduction_context = INCOMING_REDUCTION_CONTEXT.get(stat)
            previous_reduction = (
                api.damage_taken_reduction_total(target, *reduction_context)
                if reduction_context is not None else None
            )
            matching = [
                modifier for modifier in target.modifiers
                if modifier.source_actor == actor.name
                and modifier.source_skill == self.name
                and modifier.name == effect_identity
                and modifier.stat == stat
            ]
            if matching and not stackable:
                matching[0].value = value
                matching[0].expires_after_turn = expires_after_turn
                matching[0].source_timing = self.timing
                matching[0].end_of_round_decay = float((effect or {}).get("end_of_round_decay", 0.0) or 0.0)
                if tracks_official_attribute:
                    api.on_attribute_changed(
                        target,
                        changed_stat,
                        previous_attribute_value,
                        target.stat(changed_stat),
                        self.name,
                    )
                api.log_event(
                    f"{target.name} 的「{self.name}」【{_modifier_label(stat)}】持续时间已刷新"
                    f"，当前{_modifier_label(stat)}{_format_modifier_result_for_target(api, target, stat)}"
                )
                if notify_attribute_reduction and stat in OFFICIAL_ATTRIBUTE_STATS and value < 0:
                    api.on_attribute_reduced(actor, target, self.name)
                continue
            elif max_stacks is not None and len(matching) >= max_stacks:
                for modifier in matching:
                    modifier.expires_after_turn = expires_after_turn
                api.log_event(
                    f"{target.name} 的「{self.name}」【{_modifier_label(stat)}】已满{max_stacks}层，持续时间已刷新"
                    f"，当前{_modifier_label(stat)}{_format_modifier_result_for_target(api, target, stat)}"
                )
                continue
            else:
                target.modifiers.append(
                    Modifier(
                        effect_identity,
                        stat,
                        value,
                        expires_after_turn=expires_after_turn,
                        source_actor=actor.name,
                        source_skill=self.name,
                        source_timing=self.timing,
                        end_of_round_decay=float((effect or {}).get("end_of_round_decay", 0.0) or 0.0),
                    )
                )
            if tracks_official_attribute:
                current_value = target.stat(changed_stat)
                api.on_attribute_changed(target, changed_stat, previous_attribute_value, current_value, self.name)
            label = _modifier_label(stat)
            direction = "提升" if value >= 0 else "降低"
            if stat in STAT_NAME_MAP.values():
                result = target.stat(stat)
            elif stat == "damage_dealt_bonus":
                result = min(1.0, max(0.0, target.damage_bonus + target.modifier_total(stat)))
            elif stat in {"weapon_damage_bonus", "strategy_damage_bonus"}:
                result = min(
                    1.0,
                    max(0.0, target.damage_bonus + target.modifier_total("damage_dealt_bonus"))
                    + max(0.0, target.modifier_total(stat)),
                )
            elif stat in INCOMING_REDUCTION_CONTEXT:
                kind, timing = INCOMING_REDUCTION_CONTEXT[stat]
                result = api.damage_taken_reduction_total(target, kind, timing)
            else:
                result = target.modifier_total(stat)
            applied_value = result - previous_reduction if previous_reduction is not None else abs(value)
            api.log_event(
                f"{target.name} 的【{label}】{direction}{_format_modifier_value(stat, applied_value)}"
                f"（{_format_modifier_result(stat, result)}）"
            )
            if notify_attribute_reduction and stat in OFFICIAL_ATTRIBUTE_STATS and value < 0:
                api.on_attribute_reduced(actor, target, self.name)

    def _add_status(
        self,
        api: BattleApi,
        target: General,
        actor: General,
        status_name: str,
        duration: int | None,
        effect: dict[str, Any] | None = None,
    ) -> None:
        if target.has_status(f"{status_name}免疫"):
            api.log_event(f"{target.name} 免疫 {status_name}")
            return
        payload: dict[str, Any] = {"source_timing": self.timing.value}
        if status_name in {"焚烧", "中毒", "流血", "鸩毒"}:
            payload["power"] = 0.60
        if effect:
            payload.update({key: value for key, value in effect.items() if isinstance(value, (int, float))})
        payload["source_skill"] = self.name
        matching = next(
            (
                status for status in target.statuses
                if status.name == status_name
                and status.source_actor == actor.name
                and status.payload.get("source_skill") == self.name
            ),
            None,
        )
        known_max_stacks = self._state_max_stacks(status_name)
        stackable = bool(
            (effect or {}).get("stackable")
            or (effect or {}).get("max_stacks")
            or "stacking" in str((effect or {}).get("kind", ""))
            or str((effect or {}).get("kind", "")) in {"gain_stack", "stack", "add_state_stack"}
            or known_max_stacks
        )
        if matching is not None and not stackable:
            matching.remaining_rounds = duration
            matching.payload.update(payload)
            api.log_event(f"{target.name} 的「{status_name}」持续时间已刷新")
            api.on_status_applied(actor, target, status_name)
            return
        before = target.status(status_name)
        before_stacks = before.stacks if before is not None else 0
        target.add_status(
            StatusEffect(
                status_name,
                remaining_rounds=duration,
                stacks=int(effect.get("stacks", 1)) if effect else 1,
                max_stacks=(
                    int(effect["max_stacks"])
                    if effect and "max_stacks" in effect
                    else known_max_stacks
                ),
                source_actor=actor.name,
                source_team=actor.team,
                payload=payload,
            )
        )
        current = target.status(status_name)
        if current is not None:
            stack_text = "已满层" if current.max_stacks is not None and current.stacks >= current.max_stacks else "已叠加"
            if current.stacks > 1 or before_stacks > 0:
                api.log_event(f"{target.name} 的「{status_name}」{stack_text}{current.stacks}次")
        api.on_status_applied(actor, target, status_name)

    def _state_max_stacks(self, status_name: str) -> int | None:
        for item in self.data_effects:
            if item.get("state") == status_name and item.get("max_stacks") is not None:
                return int(item["max_stacks"])
        return {
            "军令": 10,
            "笃行": 5,
            "狂骨": 15,
            "流血": 5,
            "焚烧": 5,
            "鸩毒": 5,
            "抵御": 2,
            "心计": 10,
            "素衣": 4,
            "据守": 3,
            "潜袭": 6,
        }.get(status_name)

    def _clear_state_effects(self, target: General, state_name: str) -> None:
        target.statuses = [status for status in target.statuses if status.name != state_name]
        state_token = f":{state_name}:"
        target.modifiers = [
            modifier
            for modifier in target.modifiers
            if not (
                modifier.source_skill == self.name
                and (state_token in modifier.name or modifier.name.endswith(f":{state_name}"))
            )
        ]

    def _layout_state_count(self, target: General) -> int:
        held = {state for state in LAYOUT_STATES if target.has_status(state)}
        if target.has_status("清醒"):
            held.add("布阵一")
        if target.has_status("抵御"):
            held.add("布阵二")
        return len(held)

    def _grant_layout_state(
        self,
        api: BattleApi,
        actor: General,
        target: General,
        state: str,
        duration: int | None,
        effect: dict[str, Any],
    ) -> None:
        self._add_status(api, target, actor, state, duration, effect)
        if state == "布阵一":
            self._add_status(api, target, actor, "清醒", duration, effect)
        elif state == "布阵二":
            self._add_status(api, target, actor, "抵御", duration, {**effect, "stacks": 1, "max_stacks": 2})
        else:
            stat_values = {
                "布阵三": ("strategy_damage_bonus", 0.08),
                "布阵四": ("strategy_critical_chance", 0.15),
                "布阵五": ("strategy_lifesteal", 0.10),
                "布阵六": ("command", 20.0),
                "布阵七": ("intellect", 20.0),
                "布阵八": ("insight_chance", 0.20),
            }
            stat, value = stat_values[state]
            self._apply_modifier(api, actor, [target], stat, value, duration, effect)

    def _apply_named_state_modifier(
        self,
        api: BattleApi,
        actor: General,
        target: General,
        state: str,
        duration: int | None,
        effect: dict[str, Any] | None = None,
    ) -> None:
        named = {
            "披坚": ("weapon_damage_taken_reduction", 0.20),
            "必中": ("sure_hit", 1.0),
            "连击率": ("combo_chance", _number_at_level_10(effect or {}, "value", fallback=0.50)),
            "心计": ("strategy_damage_bonus", 0.03),
            "神速": ("damage_dealt_bonus", 0.05),
            "洛神": ("damage_dealt_bonus", 0.25),
            "素衣": ("damage_taken_reduction", 0.15),
            "据守": ("command", 24.0),
            "潜袭": ("damage_taken_reduction", 0.03),
            "从计": ("strategy_damage_taken_reduction", 0.15),
            # 玉玺 is granted by 僭号天子. The text value is the level-10
            # baseline; the holder's later damage uses the normal damage pool.
            "玉玺": ("damage_dealt_bonus", 0.15),
            "洪水": ("command", -20.0),
            "火攻": ("intellect", -15.0),
            "风暴": ("initiative", -30.0),
            "畏惧": ("damage_taken_increase", 0.10),
            "妖术": ("critical_damage_bonus", -0.15),
        }
        if state not in named:
            return
        stat, value = named[state]
        matching_status = next(
            (
                current for current in target.statuses
                if current.name == state
                and current.source_actor == actor.name
                and current.payload.get("source_skill") == self.name
            ),
            None,
        )
        if matching_status is None:
            return
        stacks = matching_status.stacks if matching_status is not None and self._state_max_stacks(state) else 1
        modifier_effect = {
            "kind": f"state:{state}",
            "target": "持有者",
            "state": state,
        }
        self._apply_modifier(api, actor, [target], stat, value * stacks, duration=duration, effect=modifier_effect)
        if state == "神速":
            self._apply_modifier(
                api,
                actor,
                [target],
                "weapon_critical_chance",
                0.05 * stacks,
                duration=duration,
                effect=modifier_effect,
            )
        elif state == "洛神":
            api.heal(actor, target, 1.40, self.name)
        elif state == "素衣" and api.rng.random() < 0.50:
            self._add_status(api, target, actor, "抵御", duration, {"stacks": 1, "max_stacks": 2})

    def _damage_actions_from_text(self) -> list[tuple[DamageKind, float]]:
        actions: list[tuple[DamageKind, float]] = []
        for match in re.finditer(r"(\d+(?:\.\d+)?)%\s*→\s*(\d+(?:\.\d+)?)%", self.raw_text):
            window = self.raw_text[match.end() : match.end() + 36]
            prefix = self.raw_text[max(0, match.start() - 12) : match.start()]
            if "伤害" not in window or "治疗率" in prefix or "概率" in window[:8]:
                continue
            power = float(match.group(2)) / 100.0
            if "兵刃" in window:
                actions.append((DamageKind.WEAPON, power))
            if "谋略" in window:
                actions.append((DamageKind.STRATEGY, power))

        if actions:
            return actions[:2]
        if "兵刃" in self.traits or "兵刃伤害" in self.raw_text:
            return [(DamageKind.WEAPON, self.power)]
        if "谋略" in self.traits or "谋略伤害" in self.raw_text:
            return [(DamageKind.STRATEGY, self.power)]
        return []

    def _fallback_damage_power(self, kind: DamageKind) -> float:
        actions = self._damage_actions_from_text()
        for action_kind, power in actions:
            if action_kind == kind:
                return power
        return self.power

    def _fallback_heal_power(self) -> float:
        match = re.search(r"治疗率[:：]?\s*(\d+(?:\.\d+)?)%\s*→\s*(\d+(?:\.\d+)?)%", self.raw_text)
        if match:
            return float(match.group(2)) / 100.0
        return 1.0

    def _target_count(self, text: str) -> int:
        return _target_count(text)


def pick_targets(rng: Random, team: Team, count: int) -> list[General]:
    alive = team.alive_generals
    if count >= len(alive):
        return alive
    return rng.sample(alive, count)


def skills_for(actor: General, timing: SkillTiming) -> list[Skill]:
    book = _skill_book()
    return [
        book[name]
        for name in actor.skills
        if name in book and book[name].timing == timing
    ]


def _skill_book() -> dict[str, Skill]:
    if not hasattr(_skill_book, "cache"):
        setattr(_skill_book, "cache", _load_skill_book())
    return getattr(_skill_book, "cache")


def _load_skill_book() -> dict[str, Skill]:
    book = _fallback_skill_book()
    path = Path(__file__).resolve().parents[2] / "data" / "skills.json"
    if not path.exists():
        return book

    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("skills", []):
        skill = _skill_from_data(item)
        if skill is not None:
            book[skill.name] = skill
    return book


def _skill_from_data(item: dict[str, Any]) -> Skill | None:
    name = str(item.get("name", "")).strip()
    if not name:
        return None
    type_name = str(item.get("type", "主动"))
    timing = SKILL_TYPE_TIMING.get(type_name, SkillTiming.ACTIVE)
    chance = _activation_rate(item, timing)
    raw_text = str(item.get("raw_text", ""))
    effects = tuple(dict(effect) for effect in item.get("effects", []) if isinstance(effect, dict))
    traits = tuple(str(trait) for trait in item.get("traits", []))
    return Skill(
        name=name,
        timing=timing,
        chance=chance,
        effect="generic",
        power=_default_power(raw_text, traits),
        targets=_target_count(raw_text),
        duration=_duration({}, raw_text, 1),
        prepare_rounds=_prepare_rounds(raw_text),
        raw_text=raw_text,
        traits=traits,
        data_effects=effects,
        max_triggers_per_round=int(item.get("max_triggers_per_round", 0) or 0),
    )


def _fallback_skill_book() -> dict[str, Skill]:
    return {
        "仁德载世": Skill("仁德载世", SkillTiming.ACTIVE, 0.55, "heal", power=1.25, targets=2),
        "避其锐气": Skill("避其锐气", SkillTiming.COMMAND, 1.0, "team_damage_reduction", power=0.08),
        "威震华夏": Skill("威震华夏", SkillTiming.ACTIVE, 0.42, "weapon_damage", power=1.65, targets=2),
        "横扫千军": Skill("横扫千军", SkillTiming.ACTIVE, 0.38, "weapon_damage", power=1.35, targets=3),
        "乘胜追击": Skill("乘胜追击", SkillTiming.PURSUIT, 0.45, "weapon_damage", power=0.68, targets=1),
        "燕人咆哮": Skill("燕人咆哮", SkillTiming.ACTIVE, 0.45, "weapon_damage", power=1.45, targets=2),
        "破阵猛攻": Skill("破阵猛攻", SkillTiming.ACTIVE, 0.40, "reduce_enemy_command", power=1.0, targets=2, duration=2),
        "乱世奸雄": Skill("乱世奸雄", SkillTiming.COMMAND, 1.0, "team_damage_bonus", power=0.07),
        "运筹帷幄": Skill("运筹帷幄", SkillTiming.ACTIVE, 0.45, "strategy_damage", power=1.35, targets=2),
        "古之恶来": Skill("古之恶来", SkillTiming.PASSIVE, 1.0, "team_damage_reduction", power=0.05),
        "披坚执锐": Skill("披坚执锐", SkillTiming.COMMAND, 1.0, "team_damage_reduction", power=0.06),
        "虎痴": Skill("虎痴", SkillTiming.PASSIVE, 1.0, "team_damage_bonus", power=0.06),
    }


def _activation_rate(item: dict[str, Any], timing: SkillTiming) -> float:
    for key in ("activation_rate_at_level_10", "activation_rate", "trigger_chance_at_level_10", "trigger_chance"):
        value = item.get(key)
        if value is not None:
            return max(0.0, min(1.0, float(value)))
    if timing in {SkillTiming.COMMAND, SkillTiming.PASSIVE}:
        return 1.0
    if timing == SkillTiming.PURSUIT:
        return 0.60
    return 0.45


def _number_at_level_10(item: dict[str, Any], stem: str, fallback: float) -> float:
    for key in (f"{stem}_at_level_10", stem, "value_at_level_10", "trigger_chance_at_level_10", "value"):
        value = item.get(key)
        if value is not None:
            return float(value)
    return fallback


def _calibrated_value(actor: General, item: dict[str, Any], stem: str, fallback: float) -> float:
    formula = item.get("calibrated_formula")
    if isinstance(formula, dict):
        stat = STAT_NAME_MAP.get(str(formula.get("stat", "")))
        if stat and formula.get("base") is not None and formula.get("coefficient") is not None:
            value = actor.stat(stat)
            exponent = formula.get("exponent")
            if exponent is not None:
                value = value ** float(exponent)
            # Some fitted effects have a calibrated multiplier intercept in
            # addition to the text baseline. Keep the old default at 1.0 so
            # existing calibrations remain unchanged.
            multiplier = float(formula.get("multiplier_intercept", 1.0)) + float(formula["coefficient"]) * value
            multiplier_exponent = formula.get("multiplier_exponent")
            if multiplier_exponent is not None:
                multiplier = multiplier ** float(multiplier_exponent)
            return float(formula["base"]) * multiplier
        if stat and formula.get("intercept") is not None and formula.get("coefficient") is not None:
            value = actor.stat(stat)
            exponent = formula.get("exponent")
            if exponent is not None:
                value = value ** float(exponent)
            return float(formula["intercept"]) + float(formula["coefficient"]) * value
    return _number_at_level_10(item, stem, fallback)


def _is_yizu(general: General) -> bool:
    """夷族目前由数据标注；名称回退兼容旧版手写战斗配置。"""
    return general.race == "夷族" or general.name in {"孟获", "祝融夫人"}


def _duration(effect: dict[str, Any], raw_text: str, fallback: int) -> int | None:
    value = effect.get("duration_rounds") or effect.get("duration")
    if isinstance(value, (int, float)):
        return max(1, int(value))
    if "战斗结束" in str(value) or "战斗结束" in raw_text:
        return None
    match = re.search(r"持续\s*(\d+)\s*回合", raw_text)
    if match:
        return max(1, int(match.group(1)))
    match = re.search(r"(?:战斗开始)?前\s*(\d+)\s*回合", raw_text)
    if match:
        return max(1, int(match.group(1)))
    return max(1, fallback)


def _modifier_expiry(
    skill: Skill,
    round_no: int,
    duration: int | None,
    effect: dict[str, Any] | None = None,
) -> int | None:
    if duration is None:
        return None

    effect_text = skill.raw_text
    finite_effect = isinstance((effect or {}).get("duration_rounds"), (int, float)) or isinstance(
        (effect or {}).get("duration"), (int, float)
    )
    finite_text = finite_effect or bool(
        re.search(r"持续\s*\d+\s*回合", effect_text)
        or re.search(r"(?:战斗开始)?前\s*\d+\s*回合", effect_text)
    )
    if skill.timing in {SkillTiming.COMMAND, SkillTiming.PASSIVE} and not finite_text:
        return None
    # A modifier applied during a round remains active for that round; it is
    # removed by expire_modifiers at the end of its final active round.
    return round_no + max(1, duration) - (0 if round_no == 0 else 1)


def _format_modifier_result_for_target(api: BattleApi, target: General, stat: str) -> str:
    if stat in INCOMING_REDUCTION_CONTEXT:
        kind, timing = INCOMING_REDUCTION_CONTEXT[stat]
        value = api.damage_taken_reduction_total(target, kind, timing)
    else:
        value = target.modifier_total(stat)
    return _format_modifier_result(stat, value)


def _prepare_rounds(raw_text: str) -> int:
    match = re.search(r"准备\s*(\d+)\s*回合", raw_text)
    return int(match.group(1)) if match else 0


def _target_count(text: str) -> int:
    if "全体" in text:
        return 3
    if "四" in text or "4" in text:
        return 4
    if "三" in text or "3" in text:
        return 3
    if "两" in text or "二" in text or "2" in text:
        return 2
    return 1


def _default_power(raw_text: str, traits: tuple[str, ...]) -> float:
    for match in re.finditer(r"(\d+(?:\.\d+)?)%\s*→\s*(\d+(?:\.\d+)?)%", raw_text):
        window = raw_text[match.end() : match.end() + 36]
        if "伤害" in window and "概率" not in window[:8]:
            return float(match.group(2)) / 100.0
    if "兵刃" in traits or "谋略" in traits:
        return 1.2
    return 1.0


def _modifier_stat_from_kind(kind: str) -> str:
    mapping = {
        "active_skill_activation_rate_bonus": "active_chance_bonus",
        "active_skill_activation_rate_reduction": "active_chance_bonus",
        "damage_taken_reduction": "damage_taken_reduction",
        "weapon_damage_taken_reduction": "weapon_damage_taken_reduction",
        "strategy_damage_taken_reduction": "strategy_damage_taken_reduction",
        "basic_attack_damage_taken_reduction": "basic_damage_taken_reduction",
        "active_skill_damage_taken_reduction": "active_damage_taken_reduction",
        "chase_skill_damage_taken_reduction": "pursuit_damage_taken_reduction",
        "innate_skill_damage_taken_reduction": "innate_damage_taken_reduction",
        "damage_taken_increase": "damage_taken_increase",
        "damage_rate_bonus": "damage_dealt_bonus",
        "damage_dealt_bonus": "damage_dealt_bonus",
        "damage_dealt_reduction": "damage_dealt_reduction",
        "weapon_damage_bonus": "weapon_damage_bonus",
        "weapon_damage_dealt_bonus": "weapon_damage_bonus",
        "weapon_damage_dealt_reduction": "weapon_damage_dealt_reduction",
        "strategy_damage_bonus": "strategy_damage_bonus",
        "strategy_damage_dealt_bonus": "strategy_damage_bonus",
        "strategy_damage_dealt_reduction": "strategy_damage_dealt_reduction",
        "basic_attack_damage_bonus": "basic_damage_bonus",
        "active_skill_damage_bonus": "active_damage_bonus",
        "chase_damage_bonus": "pursuit_damage_bonus",
        "chase_skill_damage_bonus": "pursuit_damage_bonus",
        "follow_up_damage_bonus": "pursuit_damage_bonus",
        "skill_damage_rate_bonus": "damage_dealt_bonus",
        "active_skill_chance_bonus": "active_chance_bonus",
        "innate_active_skill_activation_rate_bonus": "active_chance_bonus",
        "chase_activation_rate_bonus": "pursuit_chance_bonus",
        "combo_rate_bonus": "combo_chance",
        "counterattack_rate_bonus": "counter_chance",
        "counterattack_damage_bonus": "counter_damage_bonus",
        "evasion_rate_bonus": "evasion_chance",
        "dodge_rate_bonus": "evasion_chance",
        "critical_rate_bonus": "critical_chance",
        "critical_chance_bonus": "critical_chance",
        "strategy_critical_chance_bonus": "strategy_critical_chance",
        "armor_pierce_bonus": "armor_pierce",
        "armor_break_bonus": "armor_pierce",
        "insight_bonus": "insight",
        "insight_rate_bonus": "insight",
        "mutiny_bonus": "weapon_lifesteal",
        "lifesteal_bonus": "strategy_lifesteal",
        "healing_received_bonus": "healing_taken_bonus",
        "force_bonus_flat": "force",
        "force_reduction_flat": "force",
        "intellect_bonus_flat": "intellect",
        "intellect_reduction_flat": "intellect",
        "initiative_bonus_flat": "initiative",
        "command_bonus": "command",
        "command_bonus_flat": "command",
        "command_reduction_flat": "command",
        "command_percent_bonus": "command_percent_bonus",
        "insight_bonus": "insight_chance",
        "state_effect_increase": "state_effect_bonus",
        "state_effect_reduction": "state_effect_reduction",
        "next_trigger_damage_rate_reduction": "next_trigger_damage_reduction",
    }
    if kind == "stat_bonus" or kind == "stat_debuff" or kind == "steal_stat":
        return ""
    return mapping.get(kind, "")


def _learned_skill_condition_multiplier(actor: General, effect: dict[str, Any]) -> int:
    condition = str(effect.get("condition", ""))
    if "每学习一个主动战法" not in condition and "每学习一个非主动战法" not in condition:
        return 1
    book = _skill_book()
    learned = [book[name] for name in actor.skills if name in book]
    if "每学习一个主动战法" in condition:
        return sum(skill.timing == SkillTiming.ACTIVE for skill in learned)
    return sum(skill.timing != SkillTiming.ACTIVE for skill in learned)


def _modifier_label(stat: str) -> str:
    labels = {
        "force": "武力",
        "intellect": "智力",
        "command": "统率",
        "initiative": "先攻",
        "force_percent_bonus": "武力",
        "intellect_percent_bonus": "智力",
        "command_percent_bonus": "统率",
        "initiative_percent_bonus": "先攻",
        "damage_dealt_bonus": "造成伤害",
        "damage_dealt_reduction": "造成伤害降低",
        "damage_taken_reduction": "受到伤害降低",
        "weapon_damage_taken_reduction": "受到兵刃伤害降低",
        "strategy_damage_taken_reduction": "受到谋略伤害降低",
        "basic_damage_taken_reduction": "受到普通攻击伤害降低",
        "active_damage_taken_reduction": "受到主动战法伤害降低",
        "pursuit_damage_taken_reduction": "受到追击战法伤害降低",
        "innate_damage_taken_reduction": "受到自带战法伤害降低",
        "damage_taken_increase": "受到伤害提升",
        "damage_taken_reduction_penalty": "减伤削减",
        "weapon_damage_bonus": "兵刃伤害",
        "strategy_damage_bonus": "谋略伤害",
        "basic_damage_bonus": "普通攻击伤害",
        "active_damage_bonus": "主动战法伤害",
        "pursuit_damage_bonus": "追击战法伤害",
        "active_chance_bonus": "主动战法发动率",
        "pursuit_chance_bonus": "追击战法发动率",
        "combo_chance": "连击率",
        "counter_chance": "反击率",
        "counter_damage_bonus": "反击伤害",
        "evasion_chance": "规避率",
        "critical_chance": "会心几率",
        "weapon_critical_chance": "会心几率",
        "strategy_critical_chance": "奇谋几率",
        "strategy_critical_damage_bonus": "奇谋伤害",
        "armor_pierce": "破甲",
        "weapon_lifesteal": "倒戈",
        "strategy_lifesteal": "攻心",
        "healing_taken_bonus": "受到治疗",
        "basic_target_weight_override": "受击权重",
    }
    return labels.get(stat, stat.replace("_", " "))


def _is_percent_modifier(stat: str) -> bool:
    return stat not in STAT_NAME_MAP.values()


INCOMING_REDUCTION_CONTEXT: dict[str, tuple[DamageKind | None, str | None]] = {
    "damage_taken_reduction": (None, None),
    "weapon_damage_taken_reduction": (DamageKind.WEAPON, None),
    "strategy_damage_taken_reduction": (DamageKind.STRATEGY, None),
    "basic_damage_taken_reduction": (DamageKind.WEAPON, "basic"),
    "active_damage_taken_reduction": (None, "active"),
    "pursuit_damage_taken_reduction": (None, "pursuit"),
    "innate_damage_taken_reduction": (None, "innate"),
}


def _format_modifier_value(stat: str, value: float) -> str:
    return f"{value:.2%}" if _is_percent_modifier(stat) else f"{value:.2f}"


def _format_modifier_result(stat: str, value: float) -> str:
    return f"{value:.2%}" if _is_percent_modifier(stat) else f"{value:.2f}"


NEGATIVE_MODIFIER_KINDS = {
    "active_skill_activation_rate_reduction",
    "force_reduction_flat",
    "intellect_reduction_flat",
    "command_reduction_flat",
}


def _fallback_modifier_value(raw_text: str, stat: str) -> float:
    for match in re.finditer(r"(\d+(?:\.\d+)?)%\s*→\s*(\d+(?:\.\d+)?)%", raw_text):
        window = raw_text[max(0, match.start() - 12) : match.end() + 18]
        if _stat_marker_matches(window, stat):
            return float(match.group(2)) / 100.0
    return 0.0


def _fallback_stat_value(raw_text: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)\s*→\s*(\d+(?:\.\d+)?)\s*点", raw_text)
    if match:
        return float(match.group(2))
    match = re.search(r"(\d+)\s*点", raw_text)
    return float(match.group(1)) if match else 0.0


def _stat_marker_matches(text: str, stat: str) -> bool:
    markers = {
        "basic_damage_bonus": ["普通攻击"],
        "active_chance_bonus": ["主动战法", "发动率"],
        "damage_dealt_bonus": ["造成伤害", "伤害提升"],
        "damage_dealt_reduction": ["造成伤害降低"],
        "weapon_damage_bonus": ["兵刃伤害"],
        "strategy_damage_bonus": ["谋略伤害"],
        "damage_taken_reduction": ["受到伤害降低", "受到伤害减少"],
        "damage_taken_increase": ["受到伤害提升"],
        "evasion_chance": ["规避"],
        "critical_chance": ["会心", "奇谋"],
        "counter_chance": ["反击率"],
        "counter_damage_bonus": ["反击伤害"],
    }
    return any(marker in text for marker in markers.get(stat, []))


def _looks_like_heal(raw_text: str) -> bool:
    return "恢复" in raw_text or "治疗率" in raw_text


def _is_harmful_state(status_name: str) -> bool:
    return status_name in {
        "震慑", "技穷", "缴械", "混乱", "嘲讽", "虚弱", "断粮", "焚烧", "中毒",
        "流血", "鸩毒", "迟滞", "凶逆", "应变", "连环", "暗事",
        "畏惧", "火攻", "洪水", "风暴", "妖术",
    }


def _text_applies_status(raw_text: str, status_name: str) -> bool:
    if status_name not in raw_text:
        return False
    for marker in (f"施加{status_name}", f"造成{status_name}", f"获得{status_name}", f"产生{status_name}"):
        if marker in raw_text:
            return True
    index = raw_text.find(status_name)
    prefix = raw_text[max(0, index - 8) : index]
    return "施加" in prefix or "获得" in prefix or "产生" in prefix


def _effect_should_run_now(effect: dict[str, Any], timing: SkillTiming, action_kind: str) -> bool:
    if timing in {SkillTiming.ACTIVE, SkillTiming.PURSUIT}:
        return True

    text = " ".join(str(effect.get(key, "")) for key in ("timing", "condition", "state"))
    if "战斗开始" in text or "战斗开始前" in text or "战斗中" in text:
        return True
    if action_kind == "modifier" and ("每学习" in text or not text.strip()):
        return True

    trigger_markers = (
        "每回合",
        "每个回合",
        "回合开始",
        "回合结束",
        "行动时",
        "受到伤害后",
        "造成伤害后",
        "普通攻击",
        "成功发动",
        "即将",
    )
    if any(marker in text for marker in trigger_markers):
        return False
    return action_kind == "modifier"


def _effect_matches_event(effect: dict[str, Any], event: str, skill_timing: SkillTiming) -> bool:
    text = " ".join(str(effect.get(key, "")) for key in ("timing", "condition"))
    kind = str(effect.get("kind", ""))
    if kind == "corresponding_attribute_bonus_flat":
        return event in {"setup", "after_damage_taken"}
    if kind == "gain_stack_at_command_threshold":
        return event == "command_threshold"
    if kind == "stacking_buff" and effect.get("state"):
        return event == "state_gained"
    if kind == "board_state_bonus":
        return event in {"setup", "action_start", "round_end"}
    if kind == "force_critical_and_heal_lowest_ally":
        return event == "before_damage_dealt"
    if str(effect.get("target", "")) in {"本次伤害", "该次伤害", "本次承担伤害", "该次承担伤害"} and _modifier_stat_from_kind(kind):
        return event == "before_damage_taken"
    if event.startswith("named:"):
        name = event.removeprefix("named:")
        return (
            f"{name}触发时" in text
            or f"触发{name}后" in text
            or (name in text and "累积触发" in text)
        )
    if event == "cast":
        if skill_timing not in {SkillTiming.ACTIVE, SkillTiming.PURSUIT}:
            return False
        reactive = ("回合开始", "回合结束", "行动时", "受到伤害", "造成伤害", "尝试发动")
        return not any(marker in text for marker in reactive)
    if event == "setup":
        if skill_timing not in {SkillTiming.PASSIVE, SkillTiming.COMMAND}:
            return False
        reactive = ("回合", "行动时", "受到伤害", "造成伤害", "普通攻击", "发动主动", "即将", "选择目标")
        if any(marker in text for marker in reactive):
            return ("战斗开始前" in text or "战斗前" in text) and not any(
                marker in text for marker in ("受到伤害", "造成伤害", "行动时")
            )
        return not text.strip() or any(marker in text for marker in ("战斗开始", "战斗中", "战斗前", "每学习", "自身为前排", "先攻每高过", "每提升"))
    if event == "round_start":
        return "回合开始" in text or "目标已有混乱状态" in text or (
            ("奇数回合" in text or "偶数回合" in text or "第3回合起" in text) and "结束" not in text and "行动" not in text
        )
    if event == "action_start":
        return "行动时" in text or "回合行动时" in text or "行动者兵力低于" in text
    if event == "action_end":
        return "行动结束" in text or "行动后" in text
    if event == "round_end":
        return "回合结束" in text or "回合结束时" in text
    if event == "after_basic_attack":
        return any(marker in text for marker in ("普通攻击后", "普通攻击之后", "成功普通攻击后", "累积进行3次普通攻击之后", "每累积进行4次普通攻击时")) or "若自身武力高于目标" in text
    if event == "before_basic_attack":
        return "普通攻击前" in text
    if event == "before_active_cast":
        return "尝试发动主动战法时" in text
    if event == "after_damage_dealt":
        return any(marker in text for marker in ("造成伤害后", "造成兵刃伤害后", "造成兵刃伤害时", "造成谋略伤害后", "伤害目标受到伤害后", "造成流血伤害后", "自身造成或受到伤害时"))
    if event == "after_damage_taken":
        return (
            "受到伤害后" in text
            or ("受到伤害时" in text and "前" not in text)
            or "累积受到" in text
            or "累计受到" in text
            or "为队友承担伤害时" in text
            or "若目标已持有畏惧效果" in text
        )
    if event == "before_damage_dealt":
        return "造成兵刃伤害前" in text or "造成谋略伤害前" in text
    if event == "before_damage_taken":
        return (
            "受到伤害前" in text
            or "受到伤害时" in text
            or ("受到" in text and "伤害前" in text)
            or "即将受到" in text
            or "即将阵亡" in text
        )
    if event == "after_critical":
        return "造成会心伤害后" in text
    if event == "after_evasion":
        return "成功规避后" in text
    if event == "after_state_applied":
        return any(marker in text for marker in ("施加畏惧时", "施加迟滞后", "施加异常状态", "施加负面状态", "施加的属性降低状态后", "被施加异常状态时", "被施加负面状态时"))
    if event == "after_attribute_reduction":
        return "自带战法施加的属性降低状态后" in text
    if event == "state_gained":
        return "获得" in text or "持有10层" in text or "持有狂骨层数" in text or "累积讨伐" in text
    if event == "after_resist_consumed":
        return "抵御消耗后" in text or "消耗2次抵御" in text
    if event == "after_resist_gained":
        return "获得抵御时" in text
    if event == "after_active_cast":
        return "成功发动主动战法后" in text or "发动主动战法时" in text or "首次发动主动战法后" in text or "敌军处于妖术状态" in text
    if event == "after_pursuit_cast":
        return "发动追击战法后" in text
    if event == "active_cast_failed":
        return "未发动主动战法" in text
    if event == "after_heal":
        return "造成恢复效果时" in text or "造成治疗后" in text
    if event == "after_damage_trigger":
        return "伤害触发后" in text or "额外伤害触发后" in text or "追伤目标持有负面状态" in text
    if event == "after_battle_damage":
        return "每造成2次自带战法伤害后" in text
    return False


def _event_owner_matches(
    owner: General,
    event: str,
    context: dict[str, Any],
    effects: tuple[dict[str, Any], ...],
) -> bool:
    text = " ".join(
        " ".join(str(effect.get(key, "")) for key in ("timing", "condition", "state"))
        for effect in effects
    )
    subject = context.get("actor")
    attacker = context.get("attacker")
    target = context.get("target")
    if event == "action_start":
        if any(effect.get("kind") == "board_state_bonus" for effect in effects):
            return isinstance(subject, General) and subject.team == owner.team
        if any(effect.get("kind") == "steal_stat" and effect.get("state") for effect in effects):
            return isinstance(subject, General) and _subject_has_owned_named_state(owner, subject, text)
        return isinstance(subject, General) and (
            subject is owner
            or (subject.team == owner.team and ("我军" in text or _subject_has_owned_named_state(owner, subject, text)))
        )
    if event == "action_end":
        if "玉玺持有者" in text:
            return (
                isinstance(subject, General)
                and subject.team == owner.team
                and subject.has_status("玉玺")
                and any(
                    status.name == "玉玺"
                    and (status.source_actor == owner.name or status.source_actor is None)
                    for status in subject.statuses
                )
            )
        return isinstance(subject, General) and (subject is owner or "我军" in text)
    if event == "after_basic_attack":
        return isinstance(subject, General) and (
            subject is owner
            or (subject.team == owner.team and ("我军" in text or _subject_has_owned_named_state(owner, subject, text)))
        )
    if event == "after_damage_dealt":
        return isinstance(attacker, General) and (
            attacker is owner
            or (
                attacker.team == owner.team
                and ("我军" in text or _subject_has_owned_named_state(owner, attacker, text))
            )
        )
    if event == "after_damage_taken":
        if not isinstance(target, General):
            return False
        if target is owner:
            return True
        if target.team != owner.team:
            return _subject_has_owned_named_state(owner, target, text)
        if "我军" not in text and target is not owner:
            return _subject_has_owned_named_state(owner, target, text)
        if "统率最高" in text:
            alive = [general for general in context.get("all_generals", []) if general.team == owner.team and general.is_alive]
            return not alive or target.stat("command") >= max(general.stat("command") for general in alive)
        if "前排" in text:
            return target.position == "front"
        return True
    if event in {"before_damage_taken", "after_evasion", "after_resist_consumed", "after_resist_gained"}:
        subject = context.get("target") or context.get("actor")
        return isinstance(subject, General) and (
            subject is owner
            or (subject.team == owner.team and ("我军" in text or "队友" in text))
        )
    if event.startswith("named:"):
        subject = context.get("actor")
        return isinstance(subject, General) and subject is owner
    if event in {"before_damage_dealt", "after_critical", "after_damage_trigger", "after_battle_damage"}:
        subject = context.get("attacker") or context.get("actor")
        return isinstance(subject, General) and (
            subject is owner
            or (
                subject.team == owner.team
                and ("我军" in text or _subject_has_owned_named_state(owner, subject, text))
            )
        )
    if event in {"after_state_applied", "state_gained"}:
        source = context.get("actor")
        target = context.get("target")
        if isinstance(source, General) and source is owner:
            return True
        return isinstance(target, General) and target.team == owner.team and "我军" in text
    if event == "after_attribute_reduction":
        source = context.get("actor")
        target = context.get("target")
        source_skill = context.get("source_skill")
        return (
            isinstance(source, General)
            and isinstance(target, General)
            and source.team == owner.team
            and target.team != owner.team
            and bool(source.skills)
            and source.skills[0] == source_skill
        )
    if event == "command_threshold":
        subject = context.get("target")
        return isinstance(subject, General) and subject is owner
    if event in {"before_active_cast", "after_active_cast", "active_cast_failed", "after_pursuit_cast", "after_heal"}:
        if event == "after_heal" and context.get("is_extra"):
            return False
        return isinstance(subject, General) and (
            subject is owner
            or (subject.team == owner.team and ("我军" in text or "队友" in text))
        )
    return True


def _event_condition_allows(
    api: BattleApi,
    actor: General,
    skill_name: str,
    effect: dict[str, Any],
    event: str,
    context: dict[str, Any],
) -> bool:
    text = f"{effect.get('timing', '')} {effect.get('condition', '')}"
    target = context.get("target")
    kind = context.get("kind")
    source = str(context.get("source", ""))
    subject = context.get("actor") or context.get("attacker")

    if "每回合首次" in text and api.trigger_count(actor, skill_name, event) > 1:
        return False

    cumulative_damage = re.search(r"每累计受到\s*(\d+)\s*兵力伤害", text)
    if cumulative_damage:
        threshold = int(cumulative_damage.group(1))
        previous = int(context.get("team_damage_taken_before", 0) or 0)
        current = int(context.get("team_damage_taken_total", previous) or previous)
        crossed = current // threshold - previous // threshold
        if crossed <= 0:
            return False
        context["cumulative_trigger_count"] = crossed

    held_layers = re.search(r"(首次)?持有\s*(\d+)\s*层([^时后，； ]+)", text)
    if held_layers:
        state_name = held_layers.group(3).removesuffix("状态")
        holder = context.get("target")
        gained_state = str(context.get("status", ""))
        if not isinstance(holder, General) or gained_state != state_name:
            return False
        state = holder.status(state_name)
        if state is None or state.stacks < int(held_layers.group(2)):
            return False
        if held_layers.group(1):
            marker_name = f"{skill_name}-{state_name}{held_layers.group(2)}层首次触发"
            if actor.has_status(marker_name):
                return False
            actor.statuses.append(
                StatusEffect(
                    marker_name,
                    remaining_rounds=None,
                    source_actor=actor.name,
                    source_team=actor.team,
                    payload={"source_skill": skill_name, "internal": True},
                )
            )

    if effect.get("kind") == "corresponding_attribute_bonus_flat":
        if event == "setup":
            return True
        damaged = context.get("target")
        if not isinstance(damaged, General) or damaged.team != actor.team:
            return False
        marker_names = {
            "武力": "百战不殆-武",
            "智力": "百战不殆-智",
            "统率": "百战不殆-统",
        }
        if not any(
            damaged.has_status(marker_names[str(raw_stat)])
            for raw_stat in effect.get("attributes", [])
            if str(raw_stat) in marker_names
        ):
            return False

    if isinstance(subject, General) and effect.get("kind") != "corresponding_attribute_bonus_flat":
        for label, stat in (("武力", "force"), ("智力", "intellect"), ("统率", "command"), ("先攻", "initiative")):
            if f"我军{label}最高单体" not in text and f"{label}最高单体" not in text:
                continue
            allies = api.allies_of(actor).alive_generals
            if allies and subject is not max(allies, key=lambda general: general.stat(stat)):
                return False

    if "造成兵刃伤害" in text and kind != DamageKind.WEAPON:
        return False
    if "造成谋略伤害" in text and kind != DamageKind.STRATEGY:
        return False
    if "造成流血伤害" in text and source != "流血":
        return False
    if "自身通过自带战法造成伤害后" in text and (not actor.skills or source != actor.skills[0]):
        return False
    if "持有连环的目标受到伤害后" in text:
        if not isinstance(target, General) or not _subject_has_owned_named_state(actor, target, text):
            return False
        if kind in {DamageKind.TRANSFER, DamageKind.DESERTER}:
            return False
    if "目标存在属性降低状态" in text:
        if not isinstance(target, General) or not any(
            modifier.value < 0 and modifier.stat in STAT_NAME_MAP.values() for modifier in target.modifiers
        ):
            return False
    if "敌军处于妖术状态" in text and not any(
        general.has_status("妖术") for general in api.enemies_of(actor).alive_generals
    ):
        return False

    basic_count = int(context.get("actor_basic_count", 0))
    team_basic_count = int(context.get("team_basic_count", 0))
    if "每累积进行4次普通攻击" in text and (team_basic_count == 0 or team_basic_count % 4 != 0):
        return False
    if "累计进行3次普通攻击" in text and (basic_count == 0 or basic_count % 3 != 0):
        return False

    named_match = re.search(r"累积触发\s*(\d+)\s*次(.+?)后", text)
    if named_match:
        required = int(named_match.group(1))
        named_count = int(context.get("named_count", 0))
        if named_count == 0 or named_count % required != 0:
            return False
    return True


def _round_condition_allows(effect: dict[str, Any], round_no: int) -> bool:
    text = f"{effect.get('timing', '')} {effect.get('condition', '')}"
    if "奇数回合" in text and round_no % 2 == 0:
        return False
    if "偶数回合" in text and round_no % 2 == 1:
        return False
    if "第4回合" in text and round_no != 4 and "起" not in text:
        return False
    if "第3回合起" in text and round_no < 3:
        return False
    if "第4回合起" in text and round_no < 4:
        return False
    starting = re.search(r"第(\d+)回合起", text)
    if starting and round_no < int(starting.group(1)):
        return False
    opening = re.search(r"(?:战斗开始)?前(\d+)回合", text)
    if opening and round_no > int(opening.group(1)):
        return False
    match = re.search(r"战斗第(\d+)[、,](\d+)回合", text)
    if match and round_no not in {int(match.group(1)), int(match.group(2))}:
        return False
    return True


def _subject_has_owned_named_state(owner: General, subject: General, text: str) -> bool:
    return any(
        status.name in text
        and (status.source_actor == owner.name or status.source_actor is None)
        for status in subject.statuses
    )


def _effect_trigger_chance(
    effect: dict[str, Any],
    round_no: int = 1,
    actor: General | None = None,
) -> float:
    for key in ("trigger_chance_at_level_10", "trigger_chance", "chance_at_level_10", "chance"):
        if effect.get(key) is not None:
            chance = float(effect[key])
            increase = float(
                effect.get(
                    "trigger_chance_increase_per_round_at_level_10",
                    effect.get("trigger_chance_increase_per_round", 0.0),
                )
                or 0.0
            )
            reduction = float(effect.get("trigger_chance_reduction_per_round", 0.0) or 0.0)
            chance += (increase - reduction) * max(0, round_no - 1)
            if actor is not None and effect.get("trigger_chance_bonus_per_qianxi_stack") is not None:
                qianxi = actor.status("潜袭")
                chance += float(effect["trigger_chance_bonus_per_qianxi_stack"]) * (qianxi.stacks if qianxi else 0)
            return max(0.0, min(1.0, chance))
    return 1.0


def _uses_per_target_chance(effect: dict[str, Any]) -> bool:
    return bool(
        effect.get("each_target_independent")
        or effect.get("independent_judgment")
        or effect.get("independent_judgment_per_target")
        or effect.get("independent_judgment_per_general")
        or effect.get("per_general_independent_judgement")
    ) or str(effect.get("kind", "")) in {
        "apply_state",
        "grant_state",
        "apply_random_control_state",
        "apply_random_state",
        "apply_random_unique_state",
        "extra_apply_random_unique_state",
    }


def _roll_effect(api: BattleApi, effect: dict[str, Any], actor: General | None = None) -> bool:
    chance = _effect_trigger_chance(effect, api.round_no, actor)
    return chance >= 1.0 or api.rng.random() < chance


def _roll_effect_for_target(
    api: BattleApi,
    effect: dict[str, Any],
    target: General | None = None,
    actor: General | None = None,
) -> bool:
    chance = _effect_trigger_chance(effect, api.round_no, actor)
    if target is not None and effect.get("trigger_chance_bonus_per_target_abnormal_state") is not None:
        abnormal_count = sum(target.has_status(state) for state in ABNORMAL_STATUSES)
        maximum = int(effect.get("max_bonus_count", abnormal_count) or abnormal_count)
        chance += float(effect["trigger_chance_bonus_per_target_abnormal_state"]) * min(abnormal_count, maximum)
    chance = max(0.0, min(1.0, chance))
    return chance >= 1.0 or api.rng.random() < chance


def _damage_kind_for_effect(effect: dict[str, Any], actor: General, kind: str) -> DamageKind:
    if kind in {"weapon_damage", "triggered_weapon_damage", "extra_weapon_damage", "follow_up_weapon_damage"}:
        return DamageKind.WEAPON
    if kind == "strategy_damage":
        return DamageKind.STRATEGY
    damage_kind = str(effect.get("damage_kind", ""))
    if "兵刃" in damage_kind:
        return DamageKind.WEAPON
    if "谋略" in damage_kind:
        return DamageKind.STRATEGY
    return DamageKind.WEAPON if actor.stat("force") >= actor.stat("intellect") else DamageKind.STRATEGY


def _target_condition_allows(
    effect: dict[str, Any],
    actor: General,
    target: General,
    preexisting_statuses: dict[int, set[str]],
) -> bool:
    condition = f"{effect.get('timing', '')} {effect.get('condition', '')}"
    statuses = preexisting_statuses.get(id(target), set())
    for status in KNOWN_STATUSES + ["属性降低", "控制"]:
        if status not in condition:
            continue
        if "未" in condition and status in statuses:
            return False
        if any(marker in condition for marker in ("已持有", "已处于", "持有", "处于")) and "未" not in condition:
            if status == "控制":
                if not any(name in statuses for name in CONTROL_STATUSES):
                    return False
            elif status == "属性降低":
                if not any(mod.value < 0 for mod in target.modifiers):
                    return False
            elif status not in statuses:
                return False
    if "自身武力高于目标" in condition or "目标武力低于自身" in condition:
        return actor.stat("force") > target.stat("force")
    if "目标武力不大于智力" in condition:
        return target.stat("force") <= target.stat("intellect")
    if "目标武力大于智力" in condition:
        return target.stat("force") > target.stat("intellect")
    if "自身先攻大于目标" in condition:
        return actor.stat("initiative") > target.stat("initiative")
    if "自身为前排" in condition:
        return actor.position == "front"
    if "目标为后排" in condition:
        return target.position == "back"
    if "目标为前排" in condition:
        return target.position == "front"
    return True


def _cleanse_negative_states(target: General, count: int) -> None:
    harmful = [status for status in target.statuses if _is_harmful_state(status.name)]
    removed = harmful[: max(0, count)]
    remove_ids = {id(status) for status in removed}
    target.statuses = [status for status in target.statuses if id(status) not in remove_ids]
    removed_tokens = {
        (str(status.payload.get("source_skill", "")), f":{status.name}:")
        for status in removed
    }
    target.modifiers = [
        modifier for modifier in target.modifiers
        if not any(
            modifier.source_skill == source and token in modifier.name
            for source, token in removed_tokens
        )
    ]


def _functional_buff_count(target: General) -> int:
    return len({
        status.name
        for status in target.statuses
        if status.stacks > 0
        and not _is_harmful_state(status.name)
        and not status.payload.get("internal")
    })


def _stat_values(effect: dict[str, Any], raw_text: str, actor: General) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    raw_stats = effect.get("stats")
    if isinstance(raw_stats, dict):
        for raw_name, config in raw_stats.items():
            stat = STAT_NAME_MAP.get(str(raw_name), str(raw_name))
            if isinstance(config, dict):
                value = _calibrated_value(actor, config, "value", fallback=0.0)
            else:
                value = float(config)
            values.append((stat, value))
        return values
    names = raw_stats if isinstance(raw_stats, list) else [effect.get("stat", "")]
    value = _calibrated_value(actor, effect, "value", fallback=_fallback_stat_value(raw_text))
    for raw_name in names:
        stat = STAT_NAME_MAP.get(str(raw_name), str(raw_name))
        if stat:
            values.append((stat, value))
    return values
