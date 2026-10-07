from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from random import Random
from typing import Any, Iterable

from .models import Battle, BattleResult, DamageKind, General, Modifier, SkillTiming, SourceStat, StatusEffect, Team
from .skills import Skill, skills_for


CONTROL_STUN = "震慑"
CONTROL_SILENCE = "技穷"
CONTROL_DISARM = "缴械"
CONTROL_CONFUSION = "混乱"
CONTROL_TAUNT = "嘲讽"
CONTROL_WEAKEN = "虚弱"
CONTROL_STARVE = "断粮"
STATUS_RESIST = "抵御"
STATUS_SURE_HIT = "必中"
STATUS_PIERCE_RESIST = "破御"
DOT_STATUSES = {"焚烧": DamageKind.STRATEGY, "中毒": DamageKind.STRATEGY, "流血": DamageKind.WEAPON}
CRITICAL_BASE_MULTIPLIER = 1.50
WEAPON_FORCE_SLOPE = 181.246541
WEAPON_FORCE_OFFSET = 177.097104
WEAPON_HIGH_FORCE_SLOPE = 633.945615
WEAPON_FORCE_BREAKPOINT = 350.0
WEAPON_FORCE_TRANSITION = 42.229892
WEAPON_COMMAND_OFFSET = 76.751897
WEAPON_BASE_CONSTANT = 34.118963
# PVP 赵云普攻与龙胆样本回代得到的暂定破甲参数。
ARMOR_PIERCE_COMMAND_PER_POINT = 5.285313
# 草船借箭看破样本更符合按目标智力比例削减；参数中的 insight 使用 0~1 比例。
INSIGHT_TARGET_INTELLECT_RATE = 0.436802
NEGATIVE_STATUSES = {
    "震慑", "技穷", "缴械", "混乱", "嘲讽", "虚弱", "断粮", "焚烧", "中毒", "流血",
    "畏惧", "火攻", "洪水", "风暴", "妖术", "迟滞", "怯战", "属性降低", "属性降低状态",
}
DISPLAY_MODIFIERS = {
    "force": "武力",
    "intellect": "智力",
    "command": "统率",
    "initiative": "先攻",
    "damage_dealt_bonus": "造成伤害",
    "damage_dealt_reduction": "造成伤害降低",
    "damage_taken_reduction": "受到伤害降低",
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
    "damage_against_front_bonus": "对前排伤害",
    "evasion_chance": "规避率",
    "critical_chance": "会心几率",
    "weapon_critical_chance": "会心几率",
    "strategy_critical_chance": "奇谋几率",
    "critical_damage_bonus": "会心与奇谋伤害",
    "strategy_critical_damage_bonus": "奇谋伤害",
    "weapon_damage_taken_reduction": "受到兵刃伤害降低",
    "strategy_damage_taken_reduction": "受到谋略伤害降低",
    "basic_damage_taken_reduction": "受到普通攻击伤害降低",
    "active_damage_taken_reduction": "受到主动战法伤害降低",
    "pursuit_damage_taken_reduction": "受到追击战法伤害降低",
    "innate_damage_taken_reduction": "受到自带战法伤害降低",
    "deserter_damage_taken_reduction": "受到逃兵伤害降低",
    "transfer_damage_taken_reduction": "受到传递伤害降低",
    "armor_pierce": "破甲",
    "insight": "看破",
    "weapon_lifesteal": "倒戈",
    "strategy_lifesteal": "攻心",
    "healing_dealt_bonus": "治疗效果",
    "healing_taken_bonus": "受到治疗",
    "basic_target_weight_override": "受击权重",
}

HEAL_INTELLIGENCE_LINEAR = 0.057852017705361004
HEAL_INTELLIGENCE_QUADRATIC = 0.0025656781281244993
HEAL_INTELLIGENCE_CONSTANT = 116.50565586183703
FORGOT_SELF_HELP_INTEL_FACTOR = 0.68
FORGOT_SELF_HELP_COMMAND_FACTOR = 0.4125


def _heal_reference_factor(value: float) -> float:
    return value * (HEAL_INTELLIGENCE_LINEAR + HEAL_INTELLIGENCE_QUADRATIC * value) + HEAL_INTELLIGENCE_CONSTANT


class BattleSimulator:
    def __init__(self, battle: Battle, seed: int | None = None) -> None:
        self.battle = battle
        self.rng = Random(seed)
        self.round_no = 0
        self.log: list[str] = []
        self.log_entries: list[dict[str, Any]] = []
        self.source_stats: dict[tuple[str, str, str], SourceStat] = {}
        self.trigger_counts: dict[tuple[int, str, str, str], int] = {}
        self.event_counts: dict[tuple[str, str], int] = {}
        self.damage_totals: dict[str, int] = {}
        self.event_depth = 0
        self.last_damage_was_critical = False
        self.snapshots: list[dict[str, Any]] = []
        self.defeated_generals: set[str] = set()
        self.command_thresholds: dict[str, dict[str, float | int]] = {}

    def run(self) -> BattleResult:
        self._initialize_source_stats()
        self._apply_setup_phase()
        self._initialize_command_thresholds()
        self._capture_snapshot("战前效果结算后")

        for round_no in range(1, self.battle.max_rounds + 1):
            self.round_no = round_no
            self.log_event(f"== 第 {round_no} 回合 ==")
            self._trigger_event("round_start")
            self._capture_snapshot(f"第 {round_no} 回合开始")

            for actor in self._action_order():
                if self._has_winner() or not actor.is_alive:
                    continue
                actor.purge_expired_statuses()
                self._take_turn(actor)
                self._capture_snapshot(f"第 {round_no} 回合 · {actor.name} 行动后")

            self._round_end()
            if self._has_winner():
                break

        return BattleResult(
            winner_name=self._winner_name(),
            rounds=self.round_no,
            teams=(deepcopy(self.battle.team_a), deepcopy(self.battle.team_b)),
            log=list(self.log),
            stats=[deepcopy(stat) for stat in self.source_stats.values()],
            snapshots=deepcopy(self.snapshots),
            log_entries=deepcopy(self.log_entries),
        )

    def run_campaign(self, max_battles: int = 8) -> list[BattleResult]:
        results: list[BattleResult] = []
        for battle_index in range(1, max_battles + 1):
            self._reset_transient_state()
            result = self.run()
            results.append(result)
            self._settle_post_battle(result.winner_name)
            if result.winner_name != "平局":
                break
            if battle_index == max_battles:
                for general in self._all_generals():
                    general.dead_troops += general.troops
                    general.troops = 0
                    self._on_general_defeated(general)
                self.log_event("连续平局至上限，双方兵疲意阻")
        return results

    def enemies_of(self, actor: General) -> Team:
        return self.battle.team_b if actor.team == self.battle.team_a.name else self.battle.team_a

    def allies_of(self, actor: General) -> Team:
        return self.battle.team_a if actor.team == self.battle.team_a.name else self.battle.team_b

    def log_event(self, message: str) -> None:
        self.log.append(message)
        states: dict[str, list[dict[str, Any]]] = {}
        for general in self._all_generals():
            if general.name not in message:
                continue
            snapshot = self._snapshot_general(general)
            snapshot["team"] = general.team
            states.setdefault(general.name, []).append(snapshot)
        self.log_entries.append({"text": message, "states": states})

    def record_damage(self, actor: General, source: str, amount: int) -> None:
        if amount > 0:
            self._source_stat(actor, source).damage += amount

    def record_activation(self, actor: General, source: str) -> None:
        self._source_stat(actor, source).activations += 1

    def consume_trigger(self, actor: General, source: str, event: str, limit: int | None = None) -> bool:
        key = (self.round_no, actor.name, source, event)
        count = self.trigger_counts.get(key, 0)
        if limit is not None and count >= limit:
            return False
        self.trigger_counts[key] = count + 1
        return True

    def trigger_count(self, actor: General, source: str, event: str) -> int:
        return self.trigger_counts.get((self.round_no, actor.name, source, event), 0)

    def event_count(self, actor: General, event: str) -> int:
        return self.event_counts.get((f"round:{self.round_no}:{actor.team}:{actor.name}", event), 0)

    def record_healing(self, actor: General, source: str, amount: int) -> None:
        if amount > 0:
            self._source_stat(actor, source).healing += amount

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
    ) -> int:
        if not actor.is_alive or not target.is_alive:
            return 0
        # Ordinary damage effects are hostile by definition. A same-team
        # target here is a target-resolution bug; redirected damage still
        # works because the attacker remains on the opposing team.
        if actor.team == target.team:
            return 0
        effect_owner = effect_owner or actor

        bypass_evasion = kind == DamageKind.DESERTER or actor.has_status(STATUS_SURE_HIT)
        if not bypass_evasion and self._roll(self._combined_evasion(target)):
            self.log_event(f"{target.name} 规避了 {actor.name} 的 {source}")
            self._trigger_event("after_evasion", {"actor": target, "attacker": actor, "target": target, "source": source})
            return 0

        before_context = dict(damage_context or {})
        before_context.update({
            "attacker": actor,
            "effect_owner": effect_owner,
            "target": target,
            "kind": kind,
            "source": source,
        })
        self._trigger_event("before_damage_dealt", before_context)
        damage = self._raw_damage(actor, target, power, kind, source, before_context)
        before_context["incoming_damage"] = damage
        self._trigger_event("before_damage_taken", before_context)

        redirected = before_context.get("redirect_target")
        if isinstance(redirected, General) and redirected.is_alive and redirected is not target:
            target = redirected
            before_context["target"] = target
            damage = self._raw_damage(actor, target, power, kind, source, before_context)

        current_reduction = self._combine_rates(
            [float(value) for value in before_context.get("current_damage_reductions", [])]
        )
        current_increase = sum(
            max(0.0, float(value)) for value in before_context.get("current_damage_increases", [])
        )
        current_multiplier = float(before_context.get("current_damage_multiplier", 1.0))
        damage = int(damage * max(0.05, 1.0 - current_reduction + current_increase) * max(0.0, current_multiplier))
        was_critical = float(before_context.get("critical_multiplier", 1.0)) > 1.0

        ambush = target.status("伏兵")
        if ambush is not None and kind not in {DamageKind.DESERTER, DamageKind.TRANSFER}:
            available = max(0, int(ambush.payload.get("amount", 0) or 0))
            blocked = min(available, int(damage * 0.50))
            if blocked > 0:
                damage -= blocked
                ambush.payload["amount"] = available - blocked
                self.log_event(f"{target.name} 消耗 {blocked} 伏兵抵挡伤害，剩余伏兵 {available - blocked}")
                self.settle_deserters(target, actor, blocked, str(ambush.payload.get("source_skill", "伏兵")))
                if available - blocked <= 0:
                    target.statuses = [status for status in target.statuses if status is not ambush]

        if kind not in {DamageKind.DESERTER, DamageKind.TRANSFER} and not actor.has_status(STATUS_PIERCE_RESIST):
            resist = target.status(STATUS_RESIST)
            if resist is not None:
                target.consume_status_stack(STATUS_RESIST)
                reduction = self.rng.uniform(0.70, 0.90)
                damage = int(damage * max(0.0, 1.0 - reduction))
                self.log_event(f"{target.name} 消耗 1 层抵御，此次伤害减少 {reduction:.2%}")
                self._trigger_event("after_resist_consumed", {"actor": target, "target": target})

        if before_context.get("prevent_fatal") and damage >= target.troops:
            damage = max(0, target.troops - 1)
        damage = max(1, min(target.troops, damage)) if target.troops > 1 or not before_context.get("prevent_fatal") else 0
        target.troops -= damage
        dead = int(damage * 0.20)
        target.dead_troops += dead
        target.wounded_troops += damage - dead

        self.record_damage(effect_owner, source, damage)
        if effect_owner is actor:
            self.log_event(
                f"{actor.name} 使用 {source} 对 {target.name} 造成 {damage} {self._damage_label(kind)}伤害"
                f"（{target.troops}）"
            )
        else:
            self.log_event(
                f"{effect_owner.name} 发动 {source}，令 {actor.name} 对 {target.name} "
                f"造成 {damage} {self._damage_label(kind)}伤害（{target.troops}）"
            )
        if not target.is_alive:
            self._on_general_defeated(target)
        self._apply_lifesteal(actor, damage, kind)
        for request in before_context.get("post_damage_heals", []):
            healer = request.get("actor")
            if not isinstance(healer, General) or not healer.is_alive:
                continue
            wounded = [
                general
                for general in self.allies_of(healer).alive_generals
                if general.troops < general.healable_max_troops()
            ]
            if wounded:
                heal_target = min(wounded, key=lambda general: general.troops / max(1, general.max_troops))
                self.heal_fixed(
                    healer,
                    heal_target,
                    int(damage * float(request.get("portion", 0.0))),
                    str(request.get("source", source)),
                    is_extra=True,
                )
        context = {
            "attacker": actor,
            "effect_owner": effect_owner,
            "target": target,
            "damage": damage,
            "kind": kind,
            "source": source,
        }
        if was_critical:
            self._trigger_event("after_critical", context)
        self._trigger_event("after_damage_dealt", context)
        self._trigger_event("after_damage_taken", context)
        self._trigger_event("after_damage_trigger", context)
        self._trigger_event("after_battle_damage", context)
        return damage

    def heal(self, actor: General, target: General, power: float, source: str) -> int:
        if not actor.is_alive or not target.is_alive:
            return 0
        healable_missing = target.healable_max_troops() - target.troops
        if healable_missing <= 0:
            return 0

        bonus = 1.0 + actor.modifier_total("healing_dealt_bonus") + target.modifier_total("healing_taken_bonus")
        intellect = actor.stat("intellect")
        if source == "忘私相助":
            attribute_factor = (
                FORGOT_SELF_HELP_INTEL_FACTOR * _heal_reference_factor(intellect)
                + FORGOT_SELF_HELP_COMMAND_FACTOR * _heal_reference_factor(actor.stat("command"))
            )
        else:
            attribute_factor = _heal_reference_factor(intellect)
        amount = int(power * attribute_factor * max(0.0, bonus))
        return self.heal_fixed(actor, target, amount, source)

    def settle_deserters(self, actor: General, target: General, amount: int, source: str) -> int:
        if not actor.is_alive or not target.is_alive:
            return 0
        reduction = self._combine_rates(self._modifier_values(target, "deserter_damage_taken_reduction"))
        amount = int(amount * max(0.0, 1.0 - reduction))
        amount = max(1, min(target.troops, int(amount)))
        target.troops -= amount
        dead = int(amount * 0.20)
        target.dead_troops += dead
        target.wounded_troops += amount - dead
        self.record_damage(actor, source, amount)
        self.log_event(
            f"{actor.name} 的【{source}】使 {target.name} 产生 {amount} 逃兵，"
            f"立即损失 {amount} 兵力（{target.troops}）"
        )
        if not target.is_alive:
            self._on_general_defeated(target)
        context = {
            "attacker": actor,
            "effect_owner": actor,
            "target": target,
            "damage": amount,
            "kind": DamageKind.DESERTER,
            "source": source,
        }
        self._trigger_event("after_damage_dealt", context)
        self._trigger_event("after_damage_taken", context)
        self._trigger_event("after_damage_trigger", context)
        self._trigger_event("after_battle_damage", context)
        return amount

    def heal_fixed(self, actor: General, target: General, amount: int, source: str, is_extra: bool = False) -> int:
        if not actor.is_alive or not target.is_alive:
            return 0
        if self._has_active_control(target, CONTROL_STARVE):
            amount = int(amount * 0.30)
        healable_missing = target.healable_max_troops() - target.troops
        amount = max(0, min(healable_missing, int(amount)))
        target.troops += amount
        target.wounded_troops = max(0, target.wounded_troops - amount)
        self.record_healing(actor, source, amount)
        self.log_event(f"{actor.name} 使用 {source} 恢复 {target.name} {amount} 兵力")
        if amount > 0:
            self._trigger_event(
                "after_heal",
                {"actor": actor, "target": target, "healing": amount, "source": source, "is_extra": is_extra},
            )
        return amount

    def pick_damage_targets(self, actor: General, count: int) -> list[General]:
        if self._has_active_control(actor, CONTROL_CONFUSION):
            candidates = [general for general in self._all_generals() if general.is_alive and general is not actor]
            return self._weighted_sample(candidates, count)
        return self.pick_targets(self.enemies_of(actor), count)

    def pick_targets(self, team: Team, count: int, exclude: General | None = None) -> list[General]:
        candidates = [general for general in team.alive_generals if general is not exclude]
        return self._weighted_sample(candidates, count)

    def _apply_setup_phase(self) -> None:
        self.round_no = 0
        self._apply_faction_bonuses()
        self._apply_troop_bonuses()
        for actor in self._all_generals():
            for skill in skills_for(actor, SkillTiming.PASSIVE):
                skill.apply_setup(self, actor)

        command_actors = sorted(
            [actor for actor in self._all_generals() if actor.is_alive],
            key=lambda actor: actor.stat("initiative"),
            reverse=True,
        )
        for actor in command_actors:
            for skill in skills_for(actor, SkillTiming.COMMAND):
                skill.apply_setup(self, actor)

    def _apply_faction_bonuses(self) -> None:
        for team in (self.battle.team_a, self.battle.team_b):
            faction_counts: dict[str, int] = {}
            for general in team.generals:
                if general.faction in {"魏", "蜀", "吴", "群"}:
                    faction_counts[general.faction] = faction_counts.get(general.faction, 0) + 1
                general.modifiers = [
                    modifier for modifier in general.modifiers if modifier.source_skill != "阵营加成"
                ]

            same_faction_count = max(faction_counts.values(), default=0)
            bonus = 0.10 if same_faction_count >= 3 else 0.05 if same_faction_count >= 2 else 0.0
            if bonus <= 0:
                self.log_event(f"{team.name} 阵营加成：三名武将来自不同阵营，无属性加成")
                continue

            faction = max(faction_counts, key=faction_counts.get)
            self.log_event(
                f"{team.name} 阵营加成：{same_faction_count}名{faction}武将，"
                f"全体武将武力、智力、统率、先攻提升{bonus:.0%}"
            )
            for general in team.generals:
                for stat in ("force", "intellect", "command", "initiative"):
                    general.modifiers.append(
                        Modifier(
                            "阵营加成",
                            f"{stat}_percent_bonus",
                            bonus,
                            source_actor=team.name,
                            source_skill="阵营加成",
                        )
                    )
                self.log_event(
                    f"{general.name} 获得【阵营加成】："
                    f"武力、智力、统率、先攻提升{bonus:.0%}"
                )

    def _apply_troop_bonuses(self) -> None:
        bonus_table = {
            "盾兵": {"damage_taken_reduction": {2: 0.035, 3: 0.05}},
            "弓兵": {"damage_dealt_bonus": {2: 0.035, 3: 0.05}},
            "枪兵": {
                "damage_dealt_bonus": {2: 0.021, 3: 0.03},
                "damage_taken_reduction": {2: 0.014, 3: 0.02},
            },
            "骑兵": {
                "damage_dealt_bonus": {2: 0.014, 3: 0.02},
                "damage_taken_reduction": {2: 0.021, 3: 0.03},
            },
        }

        for team in (self.battle.team_a, self.battle.team_b):
            troop_counts: dict[str, int] = {}
            for general in team.generals:
                general.modifiers = [
                    modifier for modifier in general.modifiers if modifier.source_skill != "兵种加成"
                ]
                if general.troop_type in bonus_table:
                    troop_counts[general.troop_type] = troop_counts.get(general.troop_type, 0) + 1

            for troop_type, count in troop_counts.items():
                if count < 2:
                    continue
                tier = 3 if count >= 3 else 2
                effect_parts: list[str] = []
                for stat, tier_values in bonus_table[troop_type].items():
                    value = tier_values[tier]
                    for general in team.generals:
                        general.modifiers.append(
                            Modifier(
                                "兵种加成",
                                stat,
                                value,
                                source_actor=team.name,
                                source_skill="兵种加成",
                            )
                        )
                    label = "造成伤害提升" if stat == "damage_dealt_bonus" else "受到伤害降低"
                    effect_parts.append(f"{label}{value:.1%}")

                self.log_event(
                    f"{team.name} 兵种加成：{count}名{troop_type}，全体武将"
                    + "、".join(effect_parts)
                )

    def _take_turn(self, actor: General) -> None:
        if self._has_active_control(actor, CONTROL_STUN):
            self.log_event(f"{actor.name} 处于震慑，跳过行动")
            return

        self._trigger_action_states(actor)
        self._trigger_event("action_start", {"actor": actor})

        if self._has_active_control(actor, CONTROL_SILENCE):
            actor.clear_preparations()
            self.log_event(f"{actor.name} 处于技穷，跳过主动战法")
        else:
            for skill in skills_for(actor, SkillTiming.ACTIVE):
                self._trigger_event("before_active_cast", {"actor": actor, "skill": skill})
                self._try_active_skill(actor, skill)
                if self._has_winner() or not actor.is_alive:
                    return

        self._trigger_event("before_basic_attack", {"actor": actor})
        basic_damage = self._try_basic_attack(actor)
        if basic_damage <= 0:
            self._trigger_event("action_end", {"actor": actor})
            return

        for skill in skills_for(actor, SkillTiming.PURSUIT):
            cast = skill.try_cast(self, actor)
            if cast:
                self._trigger_event("after_pursuit_cast", {"actor": actor, "skill": skill})
            if self._has_winner():
                return
        self._trigger_event("action_end", {"actor": actor})

    def _try_active_skill(self, actor: General, skill: Skill) -> bool:
        if skill.prepare_rounds <= 0:
            cast = skill.try_cast(self, actor)
            if cast:
                self._trigger_event("after_active_cast", {"actor": actor, "skill": skill})
            else:
                self._trigger_event("active_cast_failed", {"actor": actor, "skill": skill})
            return cast

        progress = actor.preparations.get(skill.name, 0)
        if progress <= 0:
            chance = max(0.0, min(1.0, skill.chance + actor.modifier_total("active_chance_bonus")))
            if not self._roll(chance):
                self._trigger_event("active_cast_failed", {"actor": actor, "skill": skill})
                return False
            skip = actor.status("下次准备战法跳过准备")
            if skip is not None:
                actor.consume_status_stack("下次准备战法跳过准备")
                cast = skill.try_cast(self, actor)
                if cast:
                    self._trigger_event("after_active_cast", {"actor": actor, "skill": skill})
                return cast
            actor.preparations[skill.name] = 1
            self.log_event(f"{actor.name} 开始准备 {skill.name}")
            return True

        progress += 1
        if progress < skill.prepare_rounds + 1:
            actor.preparations[skill.name] = progress
            self.log_event(f"{actor.name} 继续准备 {skill.name}")
            return True

        del actor.preparations[skill.name]
        cast = skill.try_cast(self, actor)
        if cast:
            self._trigger_event("after_active_cast", {"actor": actor, "skill": skill})
        return cast

    def _try_basic_attack(self, actor: General) -> int:
        if self._has_active_control(actor, CONTROL_DISARM):
            self.log_event(f"{actor.name} 处于缴械，跳过普攻与追击")
            return 0
        target = self._pick_basic_attack_target(actor)
        if target is None:
            return 0

        damage = self.perform_basic_attack(actor, target)
        combo = max(0.0, min(1.0, actor.modifier_total("combo_chance")))
        if damage > 0 and combo > 0 and self._roll(combo):
            self.log_event(f"{actor.name} 触发连击")
            self.perform_basic_attack(actor)
        return damage

    def perform_basic_attack(self, actor: General, target: General | None = None, ignore_disarm: bool = False) -> int:
        if not actor.is_alive or (self._has_active_control(actor, CONTROL_DISARM) and not ignore_disarm):
            return 0
        target = target or self._pick_basic_attack_target(actor)
        if target is None or not target.is_alive:
            return 0
        self.record_activation(actor, "普通攻击")
        damage = self.deal_damage(actor, target, 1.0, DamageKind.WEAPON, "普通攻击")
        if damage > 0 and target.is_alive:
            self._try_counterattack(target, actor)
        if damage > 0:
            self._trigger_state_effects("after_basic_attack", actor, target, damage)
            self._trigger_event("after_basic_attack", {"actor": actor, "target": target, "damage": damage})
        return damage

    def cast_skill(self, actor: General, skill_name: str) -> bool:
        for timing in (SkillTiming.ACTIVE, SkillTiming.PURSUIT):
            for skill in skills_for(actor, timing):
                if skill.name == skill_name:
                    return skill.try_cast(self, actor)
        return False

    def force_cast_skill(self, actor: General, skill_name: str, context: dict[str, Any] | None = None) -> bool:
        for timing in (SkillTiming.ACTIVE, SkillTiming.PURSUIT):
            for skill in skills_for(actor, timing):
                if skill.name != skill_name or not actor.is_alive:
                    continue
                self.record_activation(actor, skill.name)
                self.log_event(f"{actor.name} 额外发动 {skill.name}")
                return skill._cast_generic(self, actor, event="cast", context=context)
        return False

    def on_status_applied(self, actor: General, target: General, status_name: str) -> None:
        context = {"actor": actor, "target": target, "status": status_name}
        self._trigger_event("after_state_applied", context)
        self._trigger_event("state_gained", context)
        if status_name == STATUS_RESIST:
            self._trigger_event("after_resist_gained", context)

    def on_attribute_reduced(self, actor: General, target: General, source_skill: str) -> None:
        self._trigger_event(
            "after_attribute_reduction",
            {"actor": actor, "target": target, "source_skill": source_skill},
        )

    def on_attribute_changed(
        self,
        target: General,
        stat: str,
        previous: float,
        current: float,
        source_skill: str | None = None,
    ) -> None:
        """Handle absolute command thresholds used by 兵动若神."""
        if stat != "command" or "兵动若神" not in target.skills:
            return
        state = self.command_thresholds.get(target.name)
        if state is None:
            return

        baseline = float(state["baseline"])
        while True:
            current_threshold = max(0, math.floor((current - baseline + 1e-9) / 60.0))
            awarded = int(state["awarded"])
            if current_threshold <= awarded:
                return
            next_threshold = awarded + 1
            state["awarded"] = next_threshold
            self.log_event(
                f"{target.name} 统率首次达到战斗初始值+{next_threshold * 60:g}，"
                f"获得第{next_threshold}个额外军令"
            )
            self._trigger_event(
                "command_threshold",
                {
                    "actor": target,
                    "target": target,
                    "stat": stat,
                    "previous": previous,
                    "current": current,
                    "threshold": next_threshold * 60,
                    "source_skill": source_skill,
                },
            )
            # 获得军令会继续提高全队统率，因此要重新判断是否跨过后续阈值。
            current = target.stat("command")

    def _initialize_command_thresholds(self) -> None:
        self.command_thresholds = {
            actor.name: {"baseline": actor.stat("command"), "awarded": 0}
            for actor in self._all_generals()
            if actor.is_alive and "兵动若神" in actor.skills
        }

    def trigger_named_event(self, actor: General, name: str, context: dict[str, Any] | None = None) -> None:
        payload = dict(context or {})
        payload["actor"] = actor
        payload["trigger_name"] = name
        self.log_event(f"{actor.name} 触发 {name}")
        self._trigger_event(f"named:{name}", payload)

    def _try_counterattack(self, defender: General, attacker: General) -> None:
        counter = defender.status("反击")
        chance = defender.modifier_total("counter_chance")
        power = max(0.1, defender.modifier_total("counter_power") or 0.72)
        if counter is not None:
            chance = max(chance, float(counter.payload.get("chance", 1.0)))
            power = float(counter.payload.get("power", power))
        if chance > 0 and self._roll(min(1.0, chance)):
            self.record_activation(defender, "反击")
            self.deal_damage(defender, attacker, power, DamageKind.WEAPON, "反击")

    def _pick_basic_attack_target(self, actor: General) -> General | None:
        if self._has_active_control(actor, CONTROL_CONFUSION):
            candidates = [general for general in self._all_generals() if general.is_alive and general is not actor]
            picked = self._weighted_sample(candidates, 1)
            return picked[0] if picked else None

        taunt = None if actor.has_status("清醒") else actor.status(CONTROL_TAUNT)
        if taunt is not None and taunt.source_actor:
            for target in self.enemies_of(actor).alive_generals:
                if target.name == taunt.source_actor:
                    return target

        picked = self.pick_targets(self.enemies_of(actor), 1)
        return picked[0] if picked else None

    def _round_end(self) -> None:
        for actor in list(self._all_generals()):
            if not actor.is_alive:
                continue
            for status_name, kind in DOT_STATUSES.items():
                status = actor.status(status_name)
                if status is None:
                    continue
                source = self._find_general(status.source_actor)
                attacker = source if source is not None and source.is_alive else actor
                power = float(status.payload.get("power", 0.60)) * max(1, status.stacks)
                self.deal_damage(attacker, actor, power, kind, status_name)

        self._trigger_event("round_end")

        for actor in self._all_generals():
            old_statuses = {status.name for status in actor.statuses}
            old_modifiers = {(modifier.name, modifier.stat) for modifier in actor.modifiers}
            for modifier in actor.modifiers:
                if modifier.end_of_round_decay > 0 and modifier.value > 0:
                    modifier.value = max(0.0, modifier.value - modifier.end_of_round_decay)
                    self.log_event(
                        f"{actor.name} 的「{modifier.source_skill or modifier.name}」"
                        f"【{DISPLAY_MODIFIERS.get(modifier.stat, modifier.stat)}】降低{modifier.end_of_round_decay:g}"
                    )
            actor.tick_status_durations()
            actor.expire_modifiers(self.round_no)
            actor.purge_expired_statuses()
            current_statuses = {status.name for status in actor.statuses}
            current_modifiers = {(modifier.name, modifier.stat) for modifier in actor.modifiers}
            for name in sorted(old_statuses - current_statuses):
                self.log_event(f"{actor.name} 的「{name}」效果已消失")
            for name, stat in sorted(old_modifiers - current_modifiers):
                display_name = str(name).split(":", 1)[0]
                self.log_event(
                    f"{actor.name} 的「{display_name}」【{DISPLAY_MODIFIERS.get(stat, stat)}】效果已消失"
                )
            if not actor.is_alive:
                self._on_general_defeated(actor)
        self._capture_snapshot(f"第 {self.round_no} 回合结束")

    def _action_order(self) -> list[General]:
        team_a = sorted(self.battle.team_a.alive_generals, key=lambda actor: actor.stat("initiative"), reverse=True)
        team_b = sorted(self.battle.team_b.alive_generals, key=lambda actor: actor.stat("initiative"), reverse=True)
        result: list[General] = []
        ia = ib = 0

        while ia < len(team_a) and ib < len(team_b):
            left = team_a[ia]
            right = team_b[ib]
            diff = left.stat("initiative") - right.stat("initiative")
            if abs(diff) > 70:
                left_first = diff > 0
            else:
                left_weight = max(1.0, left.stat("initiative"))
                right_weight = max(1.0, right.stat("initiative"))
                left_first = self.rng.random() < left_weight / (left_weight + right_weight)

            if left_first:
                result.append(left)
                ia += 1
            else:
                result.append(right)
                ib += 1

        result.extend(team_a[ia:])
        result.extend(team_b[ib:])
        self.log_event("行动顺序：" + "、".join(actor.name for actor in result))
        return result

    def _raw_damage(
        self,
        actor: General,
        target: General,
        power: float,
        kind: DamageKind,
        source: str,
        context: dict[str, Any] | None = None,
    ) -> int:
        context = context or {}
        if kind == DamageKind.DESERTER:
            reduction = self._combine_rates(self._modifier_values(target, "deserter_damage_taken_reduction"))
            return int(max(1.0, power * max(0.0, 1.0 - reduction)))
        if kind == DamageKind.TRANSFER:
            reduction = self._combine_rates(self._modifier_values(target, "transfer_damage_taken_reduction"))
            return int(max(0.0, power * max(0.0, 1.0 - reduction)))

        if kind == DamageKind.WEAPON:
            pierce = self._combine_rates(self._modifier_values(actor, "armor_pierce"))
            target_command = 0.0 if context.get("ignore_target_command") else target.stat("command")
            effective_command = max(
                0.0,
                target_command - ARMOR_PIERCE_COMMAND_PER_POINT * (pierce * 100.0),
            )
            force = actor.stat("force")
            scaled = (force - WEAPON_FORCE_BREAKPOINT) / WEAPON_FORCE_TRANSITION
            softplus = scaled if scaled > 40.0 else math.log1p(math.exp(scaled))
            base = (
                WEAPON_FORCE_SLOPE * (force + WEAPON_FORCE_OFFSET)
                + WEAPON_HIGH_FORCE_SLOPE * WEAPON_FORCE_TRANSITION * softplus
            ) / (effective_command + WEAPON_COMMAND_OFFSET) + WEAPON_BASE_CONSTANT
        else:
            target_command = 0.0 if context.get("ignore_target_command") else target.stat("command")
            target_intellect = 0.0 if context.get("ignore_target_intellect") else target.stat("intellect")
            insight_rate = max(0.0, actor.insight + actor.modifier_total("insight"))
            insight_fraction = insight_rate if insight_rate <= 1.0 else insight_rate / 100.0
            effective_intellect = max(
                0.0,
                target_intellect * (1.0 - INSIGHT_TARGET_INTELLECT_RATE * insight_fraction),
            )
            base = self._strategy_base_damage(
                actor.stat("intellect"), effective_intellect, target_command
            )

        timing = self._source_timing_name(source)
        dealt = self._damage_dealt_multiplier(actor, kind, timing)
        if target.position == "front":
            dealt *= max(0.0, 1.0 + actor.modifier_total("damage_against_front_bonus"))
        taken = self._damage_taken_multiplier(
            target,
            kind,
            timing,
            ignored_reduction=float(context.get("ignore_damage_reduction", 0.0) or 0.0),
        )
        troop_factor = self._troop_damage_factor(actor)
        if "critical_multiplier" in context:
            critical = float(context["critical_multiplier"])
        else:
            critical = self._critical_multiplier(
                actor,
                kind,
                force=bool(context.get("force_critical", False)),
                disabled=bool(context.get("cannot_critical", False)),
                chance_bonus=float(context.get("critical_chance_bonus", 0.0) or 0.0),
            )
            context["critical_multiplier"] = critical
        self.last_damage_was_critical = critical > 1.0
        damage = max(1.0, base) * power * dealt * taken * troop_factor * critical
        return int(damage)

    @staticmethod
    def _strategy_base_damage(attacker_intellect: float, target_intellect: float, target_command: float) -> float:
        value = (
            422.88527020
            + 0.62709505 * attacker_intellect
            - 0.30029221 * target_intellect
            - 0.54813767 * target_command
        )
        for breakpoint, a, b, c in (
            (120.0, 1.46788045, -0.00266870, -0.00173418),
            (200.0, -1.20322956, 0.00197171, 0.00256683),
            (500.0, 0.60127771, 0.00643166, -0.00430132),
            (540.0, 1.53798160, -0.00248899, -0.00014062),
            (620.0, 9.20652279, -0.02263491, -0.00314806),
        ):
            excess = max(attacker_intellect - breakpoint, 0.0)
            value += excess * (a + b * target_intellect + c * target_command)
        return value

    def _damage_dealt_multiplier(self, actor: General, kind: DamageKind, timing: str) -> float:
        kind_key = "weapon" if kind == DamageKind.WEAPON else "strategy"
        shared_bonus = min(
            1.0,
            max(0.0, actor.damage_bonus + actor.modifier_total("damage_dealt_bonus"))
            + max(0.0, actor.modifier_total(f"{kind_key}_damage_bonus")),
        )
        reduction = (
            actor.modifier_total("damage_dealt_reduction")
            + actor.modifier_total(f"{kind_key}_damage_dealt_reduction")
        )
        base = max(0.30, 1.0 + shared_bonus - reduction)

        factors = [base]
        timing_bonus = actor.modifier_total(f"{timing}_damage_bonus")
        timing_reduction = actor.modifier_total(f"{timing}_damage_dealt_reduction")
        if timing_bonus or timing_reduction:
            factors.append(max(0.05, 1.0 + timing_bonus - timing_reduction))
        result = 1.0
        for factor in factors:
            result *= factor
        if self._has_active_control(actor, CONTROL_WEAKEN):
            result *= 0.30
        return result

    def _has_active_control(self, actor: General, status_name: str) -> bool:
        return actor.has_status(status_name) and not actor.has_status("清醒")

    def _damage_taken_multiplier(
        self,
        target: General,
        kind: DamageKind,
        timing: str,
        ignored_reduction: float = 0.0,
    ) -> float:
        reductions = self._damage_taken_reduction_rates(target, kind, timing)
        increases: list[float] = []
        kind_key = "weapon" if kind == DamageKind.WEAPON else "strategy"
        for stat in (
            "damage_taken_increase",
            f"{kind_key}_damage_taken_increase",
            f"{timing}_damage_taken_increase",
            "damage_taken_reduction_penalty",
        ):
            increases.extend(self._modifier_values(target, stat))
        combined_reduction = self._combine_rates(reductions) * max(0.0, 1.0 - min(1.0, ignored_reduction))
        vulnerability = sum(max(0.0, value) for value in increases)
        return max(0.05, 1.0 - combined_reduction + vulnerability)

    def damage_taken_reduction_total(
        self,
        target: General,
        kind: DamageKind | None = None,
        timing: str | None = None,
    ) -> float:
        """Return the current multiplicatively combined incoming reduction."""
        return self._combine_rates(self._damage_taken_reduction_rates(target, kind, timing))

    def _damage_taken_reduction_rates(
        self,
        target: General,
        kind: DamageKind | None = None,
        timing: str | None = None,
    ) -> list[float]:
        rates = [target.damage_reduction]
        stats = ["damage_taken_reduction"]
        if kind is not None:
            kind_key = "weapon" if kind == DamageKind.WEAPON else "strategy"
            stats.append(f"{kind_key}_damage_taken_reduction")
        if timing:
            stats.append(f"{timing}_damage_taken_reduction")
        for stat in dict.fromkeys(stats):
            rates.extend(self._modifier_values(target, stat))
        return rates

    def _combined_evasion(self, target: General) -> float:
        rates = [target.evasion_chance]
        rates.extend(self._modifier_values(target, "evasion_chance"))
        for status in target.statuses:
            if "evasion_chance" in status.payload:
                rates.append(float(status.payload["evasion_chance"]))
        return self._combine_rates(rates)

    def _critical_multiplier(
        self,
        actor: General,
        kind: DamageKind,
        *,
        force: bool = False,
        disabled: bool = False,
        chance_bonus: float = 0.0,
    ) -> float:
        kind_key = "weapon" if kind == DamageKind.WEAPON else "strategy"
        bonus = actor.modifier_total("critical_damage_bonus") + actor.modifier_total(f"{kind_key}_critical_damage_bonus")
        if disabled:
            return 1.0
        if force:
            return max(1.0, CRITICAL_BASE_MULTIPLIER + bonus)
        guaranteed = actor.status("下次伤害必定会心或奇谋")
        if guaranteed is not None:
            actor.consume_status_stack("下次伤害必定会心或奇谋")
            bonus += float(guaranteed.payload.get("critical_damage_bonus", 0.0))
            return max(1.0, CRITICAL_BASE_MULTIPLIER + bonus)
        chance = (
            actor.critical_chance
            + actor.modifier_total("critical_chance")
            + actor.modifier_total(f"{kind_key}_critical_chance")
            + chance_bonus
        )
        if chance <= 0 or not self._roll(min(1.0, chance)):
            return 1.0
        return max(1.0, CRITICAL_BASE_MULTIPLIER + bonus)

    def _troop_damage_factor(self, actor: General) -> float:
        if actor.max_troops <= 0:
            return 1.0
        # Calibrated function uses current troops / maximum troops. The
        # original breakpoints 9/6/4/1/0.1 become 90/60/40/10/1 percent.
        x = max(0.0, actor.troops / actor.max_troops) * 10.0
        if x >= 9.0:
            return 1.0
        if x >= 6.0:
            return 0.063 * x + 0.433
        if x >= 4.0:
            return 0.073 * x + 0.373
        if x >= 1.0:
            return 0.8335922058966468 * (1.0 - math.exp(-0.20422439236668888 * x)) + 0.19638663729131026
        if x >= 0.1:
            return 0.3589214157800344 * (1.0 - math.exp(-1.0509781686228445 * x)) + 0.11249477230478798
        return 0.10332192473573393 * (1.0 - math.exp(-11.27882258789204 * x)) + 0.07203069815884945

    def _source_timing_name(self, source: str) -> str:
        if source == "普通攻击":
            return "basic"
        if source == "反击":
            return "counter"
        for actor in self._all_generals():
            if actor.skills and actor.skills[0] == source:
                return "innate"
            for skill in skills_for(actor, SkillTiming.ACTIVE):
                if skill.name == source:
                    return "active"
            for skill in skills_for(actor, SkillTiming.PURSUIT):
                if skill.name == source:
                    return "pursuit"
        return "damage"

    def _settle_post_battle(self, winner_name: str) -> None:
        for general in self._all_generals():
            if general.wounded_troops <= 0:
                continue
            if winner_name == "平局":
                conversion = 0.25
            elif general.team == winner_name:
                conversion = 0.10
            else:
                conversion = 0.75
            newly_dead = int(general.wounded_troops * conversion)
            general.dead_troops += newly_dead
            general.wounded_troops = max(0, general.wounded_troops - newly_dead)
            recover = min(general.wounded_troops, max(0, general.healable_max_troops() - general.troops))
            general.troops += recover
            general.wounded_troops -= recover

    def _reset_transient_state(self) -> None:
        self.round_no = 0
        self.log = []
        self.log_entries = []
        self.source_stats = {}
        self.trigger_counts = {}
        self.event_counts = {}
        self.damage_totals = {}
        self.event_depth = 0
        self.last_damage_was_critical = False
        self.snapshots = []
        self.defeated_generals = set()
        self.command_thresholds = {}
        for general in self._all_generals():
            general.statuses.clear()
            general.preparations.clear()
            general.modifiers = [
                modifier
                for modifier in general.modifiers
                if modifier.source_skill is None and modifier.expires_after_turn is None
            ]
            general.damage_bonus = 0.0
            general.damage_reduction = 0.0

    def _on_general_defeated(self, defeated: General) -> None:
        if defeated.name in self.defeated_generals:
            return

        self.defeated_generals.add(defeated.name)
        source_skills = set(defeated.skills)
        removed_effects: list[tuple[str, str, str]] = []
        for general in self._all_generals():
            removed_modifiers, removed_statuses = general.remove_skill_effects_from(
                defeated.name,
                source_skills,
            )
            removed_effects.extend(
                (
                    general.name,
                    "modifier",
                    f"「{modifier.source_skill}」【{DISPLAY_MODIFIERS.get(modifier.stat, modifier.stat)}】",
                )
                for modifier in removed_modifiers
            )
            removed_effects.extend(
                (
                    general.name,
                    "status",
                    f"「{status.payload.get('source_skill', '未知战法')}」的「{status.name}」",
                )
                for status in removed_statuses
            )

        self.log_event(f"【{defeated.name}】兵力为0，无法再战。")
        for target_name, effect_kind, effect_name in removed_effects:
            self.log_event(
                f"{target_name} 的{effect_name}效果因【{defeated.name}】无法再战而失效"
            )

    def _find_general(self, name: str | None) -> General | None:
        if not name:
            return None
        for general in self._all_generals():
            if general.name == name:
                return general
        return None

    def _source_stat(self, actor: General, source: str) -> SourceStat:
        key = (actor.team, actor.name, source)
        if key not in self.source_stats:
            self.source_stats[key] = SourceStat(team=actor.team, actor=actor.name, source=source)
        return self.source_stats[key]

    def _initialize_source_stats(self) -> None:
        for actor in self._all_generals():
            self._source_stat(actor, "普通攻击")
            for source in actor.skills:
                self._source_stat(actor, source)

    def _trigger_event(self, event: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.event_depth >= 12:
            return context or {}
        self.event_depth += 1
        try:
            payload = self._prepare_event_context(event, context)
            payload.setdefault("all_generals", self._all_generals())
            for actor in list(self._all_generals()):
                if not actor.is_alive:
                    continue
                for timing in (SkillTiming.PASSIVE, SkillTiming.COMMAND):
                    ordered = skills_for(actor, timing)
                    if event == "after_damage_dealt":
                        ordered = sorted(ordered, key=lambda skill: skill.name == payload.get("source"))
                    for skill in ordered:
                        skill.trigger(self, actor, event, payload)
            if context is not None:
                context.update(payload)
            return payload
        finally:
            self.event_depth -= 1

    def _prepare_event_context(self, event: str, context: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(context or {})
        if event == "after_evasion":
            actor = payload.get("actor")
            if isinstance(actor, General):
                key = (f"round:{self.round_no}:{actor.team}:{actor.name}", event)
                self.event_counts[key] = self.event_counts.get(key, 0) + 1
                payload["successful_evasion_count"] = self.event_counts[key]
        elif event == "after_basic_attack":
            actor = payload.get("actor")
            if isinstance(actor, General):
                actor_key = (f"actor:{actor.team}:{actor.name}", "basic_attack")
                team_key = (f"team:{actor.team}", "basic_attack")
                self.event_counts[actor_key] = self.event_counts.get(actor_key, 0) + 1
                self.event_counts[team_key] = self.event_counts.get(team_key, 0) + 1
                payload["actor_basic_count"] = self.event_counts[actor_key]
                payload["team_basic_count"] = self.event_counts[team_key]
        elif event.startswith("named:"):
            actor = payload.get("actor")
            if isinstance(actor, General):
                name = event.removeprefix("named:")
                key = (f"actor:{actor.team}:{actor.name}", f"named:{name}")
                self.event_counts[key] = self.event_counts.get(key, 0) + 1
                payload["named_count"] = self.event_counts[key]
        elif event == "after_damage_taken":
            target = payload.get("target")
            if isinstance(target, General):
                previous = self.damage_totals.get(target.team, 0)
                current = previous + int(payload.get("damage", 0))
                self.damage_totals[target.team] = current
                payload["team_damage_taken_before"] = previous
                payload["team_damage_taken_total"] = current
        return payload

    def _capture_snapshot(self, label: str) -> None:
        self.snapshots.append(
            {
                "label": label,
                "round": self.round_no,
                "log_index": len(self.log),
                "teams": [
                    {
                        "name": team.name,
                        "generals": [self._snapshot_general(general) for general in team.generals],
                    }
                    for team in (self.battle.team_a, self.battle.team_b)
                ],
            }
        )

    def _snapshot_general(self, general: General) -> dict[str, Any]:
        modifier_totals: dict[str, float] = {}
        modifier_sources: dict[str, set[str]] = {}
        effect_groups: dict[tuple[str, str, int | None], dict[str, Any]] = {}
        for modifier in general.modifiers:
            modifier_totals[modifier.stat] = modifier_totals.get(modifier.stat, 0.0) + modifier.value
            modifier_sources.setdefault(modifier.stat, set()).add(modifier.source_skill or modifier.name)
            source_name = modifier.source_skill or modifier.name
            key = (source_name, modifier.source_actor or "", modifier.expires_after_turn)
            group = effect_groups.setdefault(
                key,
                {
                    "name": source_name,
                    "source": modifier.source_actor or "",
                    "remaining_rounds": (
                        max(0, modifier.expires_after_turn - self.round_no)
                        if modifier.expires_after_turn is not None
                        else None
                    ),
                    "polarity": "positive",
                    "has_positive": False,
                    "has_negative": False,
                    "details": [],
                },
            )
            harmful = modifier.value < 0
            if modifier.stat in {"damage_dealt_reduction", "weapon_damage_dealt_reduction", "strategy_damage_dealt_reduction"}:
                harmful = modifier.value > 0
            if modifier.stat in {"damage_taken_reduction", "weapon_damage_taken_reduction", "strategy_damage_taken_reduction"}:
                harmful = modifier.value < 0
            if modifier.stat in {
                "damage_taken_increase",
                "weapon_damage_taken_increase",
                "strategy_damage_taken_increase",
                "damage_taken_reduction_penalty",
            }:
                harmful = modifier.value > 0
            if harmful:
                group["has_negative"] = True
            else:
                group["has_positive"] = True
            value = abs(modifier.value)
            formatted = f"{value:.2%}" if modifier.stat not in {"force", "intellect", "command", "initiative"} else f"{value:.2f}"
            direction = "提升" if modifier.value >= 0 else "降低"
            group["details"].append(f"{DISPLAY_MODIFIERS.get(modifier.stat, modifier.stat)}{direction}{formatted}")

        for group in effect_groups.values():
            has_positive = group.pop("has_positive")
            has_negative = group.pop("has_negative")
            if has_positive and has_negative:
                group["polarity"] = "mixed"
            elif has_negative:
                group["polarity"] = "negative"

        dealt = min(1.0, max(0.0, general.damage_bonus + modifier_totals.get("damage_dealt_bonus", 0.0)))
        weapon_dealt = min(1.0, dealt + max(0.0, modifier_totals.get("weapon_damage_bonus", 0.0)))
        strategy_dealt = min(1.0, dealt + max(0.0, modifier_totals.get("strategy_damage_bonus", 0.0)))
        raw_taken_reduction = self.damage_taken_reduction_total(general)
        vulnerability = sum(max(0.0, value) for value in self._modifier_values(general, "damage_taken_increase"))
        reduction_penalty = sum(
            max(0.0, value) for value in self._modifier_values(general, "damage_taken_reduction_penalty")
        )
        net_taken_reduction = raw_taken_reduction - vulnerability - reduction_penalty
        return {
            "name": general.name,
            "position": general.position,
            "alive": general.is_alive,
            "values": {
                "兵种": general.troop_type or "未配置",
                "阵营": general.faction or "未配置",
                "武力": round(general.stat("force"), 2),
                "智力": round(general.stat("intellect"), 2),
                "统率": round(general.stat("command"), 2),
                "先攻": round(general.stat("initiative"), 2),
                "兵力": general.troops,
                "最大兵力": general.max_troops,
                "伤兵": general.wounded_troops,
                "阵亡兵力": general.dead_troops,
            },
            "rates": {
                "造成伤害": round(dealt, 4),
                "兵刃通用增伤（实际）": round(weapon_dealt, 4),
                "谋略通用增伤（实际）": round(strategy_dealt, 4),
                "普通攻击伤害（独立）": round(modifier_totals.get("basic_damage_bonus", 0.0), 4),
                "主动战法伤害（独立）": round(modifier_totals.get("active_damage_bonus", 0.0), 4),
                "追击战法伤害（独立）": round(modifier_totals.get("pursuit_damage_bonus", 0.0), 4),
                "反击伤害（独立）": round(modifier_totals.get("counter_damage_bonus", 0.0), 4),
                "对前排伤害": round(modifier_totals.get("damage_against_front_bonus", 0.0), 4),
                "受到伤害降低": round(net_taken_reduction, 4),
                "减伤（未计易伤）": round(raw_taken_reduction, 4),
                "受到兵刃伤害降低": round(self.damage_taken_reduction_total(general, DamageKind.WEAPON), 4),
                "受到谋略伤害降低": round(self.damage_taken_reduction_total(general, DamageKind.STRATEGY), 4),
                "受到普通攻击伤害降低": round(
                    self.damage_taken_reduction_total(general, DamageKind.WEAPON, "basic"), 4
                ),
                "受到主动战法伤害降低": round(self.damage_taken_reduction_total(general, None, "active"), 4),
                "受到追击战法伤害降低": round(self.damage_taken_reduction_total(general, None, "pursuit"), 4),
                "受到自带战法伤害降低": round(self.damage_taken_reduction_total(general, None, "innate"), 4),
                "受到逃兵伤害降低": round(
                    self._combine_rates(self._modifier_values(general, "deserter_damage_taken_reduction")), 4
                ),
                "受到传递伤害降低": round(
                    self._combine_rates(self._modifier_values(general, "transfer_damage_taken_reduction")), 4
                ),
                "受到伤害提升": round(vulnerability, 4),
                "减伤削减": round(reduction_penalty, 4),
                "规避": round(self._combined_evasion(general), 4),
                "会心": round(
                    general.critical_chance
                    + modifier_totals.get("critical_chance", 0.0)
                    + modifier_totals.get("weapon_critical_chance", 0.0),
                    4,
                ),
                "奇谋": round(modifier_totals.get("strategy_critical_chance", 0.0), 4),
                "连击": round(modifier_totals.get("combo_chance", 0.0), 4),
                "倒戈": round(modifier_totals.get("weapon_lifesteal", 0.0), 4),
                "攻心": round(modifier_totals.get("strategy_lifesteal", 0.0), 4),
                "破甲": round(self._combine_rates(self._modifier_values(general, "armor_pierce")), 4),
                "看破": round(max(0.0, general.insight + general.modifier_total("insight")), 4),
            },
            "modifiers": [
                {
                    "key": stat,
                    "name": DISPLAY_MODIFIERS.get(stat, stat),
                    "value": round(value, 4),
                    "sources": sorted(modifier_sources.get(stat, set())),
                }
                for stat, value in sorted(modifier_totals.items())
            ],
            "statuses": [
                {
                    "name": status.name,
                    "polarity": "negative" if status.name in NEGATIVE_STATUSES else "positive",
                    "stacks": status.stacks,
                    "remaining_rounds": status.remaining_rounds,
                    "source": status.source_actor or "",
                }
                for status in general.statuses
                if status.stacks > 0
            ],
            "effects": list(effect_groups.values()),
        }

    def _trigger_state_effects(self, event: str, actor: General, target: General, damage: int) -> None:
        if event != "after_basic_attack":
            return
        if actor.has_status("执锐") and self._roll(0.50):
            picked = self.pick_targets(self.enemies_of(actor), 1)
            if picked:
                self.record_activation(actor, "执锐")
                self.deal_damage(actor, picked[0], 1.0, DamageKind.WEAPON, "执锐")

    def _trigger_action_states(self, actor: General) -> None:
        state = actor.status("披坚")
        if state is None:
            return
        source = self._find_general(state.source_actor) or actor
        self.record_activation(source, "披坚")
        self.heal(source, actor, 0.80, "披坚")

    def _apply_lifesteal(self, actor: General, damage: int, kind: DamageKind) -> None:
        if kind not in {DamageKind.WEAPON, DamageKind.STRATEGY}:
            return
        stat = "weapon_lifesteal" if kind == DamageKind.WEAPON else "strategy_lifesteal"
        grouped: dict[str, float] = {}
        for modifier in actor.modifiers:
            if modifier.stat != stat or modifier.value <= 0:
                continue
            source = modifier.source_skill or modifier.name
            grouped[source] = grouped.get(source, 0.0) + modifier.value
        for source, rate in grouped.items():
            missing = actor.healable_max_troops() - actor.troops
            amount = min(missing, int(damage * rate))
            if amount <= 0:
                continue
            actor.troops += amount
            actor.wounded_troops = max(0, actor.wounded_troops - amount)
            self.record_healing(actor, source, amount)
            self.log_event(f"{actor.name} 通过 {source} 恢复 {amount} 兵力")

    def _all_generals(self) -> list[General]:
        return self.battle.team_a.generals + self.battle.team_b.generals

    def _has_winner(self) -> bool:
        return self.battle.team_a.is_defeated or self.battle.team_b.is_defeated

    def _winner_name(self) -> str:
        a = self.battle.team_a
        b = self.battle.team_b
        if a.is_defeated and b.is_defeated:
            return "平局"
        if b.is_defeated:
            return a.name
        if a.is_defeated:
            return b.name
        return "平局"

    def _weighted_sample(self, candidates: list[General], count: int) -> list[General]:
        picked: list[General] = []
        pool = list(candidates)
        while pool and len(picked) < count:
            weights = [self._target_weight(general) for general in pool]
            total = sum(weights)
            if total <= 0:
                choice = self.rng.choice(pool)
            else:
                roll = self.rng.random() * total
                upto = 0.0
                choice = pool[-1]
                for general, weight in zip(pool, weights):
                    upto += weight
                    if roll <= upto:
                        choice = general
                        break
            picked.append(choice)
            pool.remove(choice)
        return picked

    def _target_weight(self, general: General) -> float:
        override = general.modifier_total("basic_target_weight_override")
        base_weight = override if override > 0 else general.basic_target_weight
        # Formation target rates are absolute selection weights. Current troop
        # count must not silently change the probability specified by the
        # formation; explicit skill targeting rules filter/override them.
        return max(0.0, base_weight)

    def _modifier_values(self, actor: General, stat: str) -> list[float]:
        return [modifier.value for modifier in actor.modifiers if modifier.stat == stat and modifier.value > 0]

    def _combine_rates(self, rates: Iterable[float]) -> float:
        remaining = 1.0
        for rate in rates:
            remaining *= 1.0 - max(0.0, min(1.0, rate))
        return 1.0 - remaining

    def _roll(self, chance: float) -> bool:
        return self.rng.random() < max(0.0, min(1.0, chance))

    def _damage_label(self, kind: DamageKind) -> str:
        return {
            DamageKind.WEAPON: "兵刃",
            DamageKind.STRATEGY: "谋略",
            DamageKind.DESERTER: "逃兵",
            DamageKind.TRANSFER: "传递",
        }[kind]


def load_battle(path: Path) -> Battle:
    data = json.loads(path.read_text(encoding="utf-8"))
    return battle_from_dict(data)


def battle_from_dict(data: dict[str, Any]) -> Battle:
    return Battle(
        team_a=_load_team(data["team_a"]),
        team_b=_load_team(data["team_b"]),
        max_rounds=int(data.get("max_rounds", 8)),
    )


def _load_team(data: dict[str, Any]) -> Team:
    formation = data.get("formation", {})
    team = Team(
        name=data["name"],
        generals=[_load_general(item) for item in data["generals"]],
        formation_id=str(formation.get("id", data.get("formation_id", ""))),
        formation_name=str(formation.get("name", data.get("formation_name", ""))),
    )
    for general in team.generals:
        general.team = team.name
    for modifier_data in data.get("modifiers", []):
        modifier = _load_modifier(modifier_data)
        for general in team.generals:
            general.modifiers.append(modifier)
    return team


def _load_general(item: dict[str, Any]) -> General:
    general = General(
        name=item["name"],
        troops=int(item["troops"]),
        force=int(item["force"]),
        intellect=int(item["intellect"]),
        command=int(item["command"]),
        initiative=int(item["initiative"]),
        skills=list(item.get("skills", [])),
        max_troops=int(item.get("max_troops", item["troops"])),
        position=str(item.get("position", "front")),
        troop_type=str(item.get("troop_type", "")),
        faction=str(item.get("faction", "")),
        race=str(item.get("race", "")),
        basic_target_weight=float(item.get("basic_target_weight", 1.0)),
        insight=float(item.get("insight", 0.0)),
        critical_chance=float(item.get("critical_chance", 0.0)),
        evasion_chance=float(item.get("evasion_chance", 0.0)),
    )
    general.modifiers.extend(_load_modifier(modifier) for modifier in item.get("modifiers", []))
    general.statuses.extend(_load_status(status) for status in item.get("statuses", []))
    return general


def _load_modifier(item: dict[str, Any]) -> Modifier:
    timing = item.get("source_timing")
    return Modifier(
        name=str(item.get("name", item.get("stat", "modifier"))),
        stat=str(item["stat"]),
        value=float(item["value"]),
        expires_after_turn=item.get("expires_after_turn"),
        source_actor=item.get("source_actor"),
        source_skill=item.get("source_skill"),
        source_timing=SkillTiming(timing) if timing else None,
        end_of_round_decay=float(item.get("end_of_round_decay", 0.0) or 0.0),
    )


def _load_status(item: dict[str, Any]) -> StatusEffect:
    return StatusEffect(
        name=str(item["name"]),
        remaining_rounds=item.get("remaining_rounds"),
        stacks=int(item.get("stacks", 1)),
        max_stacks=item.get("max_stacks"),
        source_actor=item.get("source_actor"),
        source_team=item.get("source_team"),
        payload=dict(item.get("payload", {})),
    )
