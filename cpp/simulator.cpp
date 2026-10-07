#include "simulator.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <utility>

namespace sanmou {
namespace {

constexpr const char* kStun = "震慑";
constexpr const char* kSilence = "技穷";
constexpr const char* kDisarm = "缴械";
constexpr const char* kConfusion = "混乱";
constexpr const char* kTaunt = "嘲讽";
constexpr const char* kWeaken = "虚弱";
constexpr const char* kStarve = "断粮";
constexpr const char* kResist = "抵御";
constexpr const char* kSureHit = "必中";
constexpr const char* kPierceResist = "破御";

const std::unordered_map<std::string, Skill>& skill_book() {
    static const std::unordered_map<std::string, Skill> skills = {
        {"仁德载世", {"仁德载世", SkillTiming::Active, 0.55, "heal", 1.25, 2, 1, 0, ""}},
        {"避其锐气", {"避其锐气", SkillTiming::Command, 1.0, "team_damage_reduction", 0.08, 1, 1, 0, ""}},
        {"威震华夏", {"威震华夏", SkillTiming::Active, 0.42, "weapon_damage", 1.65, 2, 1, 0, ""}},
        {"横扫千军", {"横扫千军", SkillTiming::Active, 0.38, "weapon_damage", 1.35, 3, 1, 0, ""}},
        {"乘胜追击", {"乘胜追击", SkillTiming::Pursuit, 0.45, "weapon_damage", 0.68, 1, 1, 0, ""}},
        {"燕人咆哮", {"燕人咆哮", SkillTiming::Active, 0.45, "weapon_damage", 1.45, 2, 1, 0, ""}},
        {"破阵猛攻", {"破阵猛攻", SkillTiming::Active, 0.40, "reduce_enemy_command", 1.0, 2, 2, 0, ""}},
        {"乱世奸雄", {"乱世奸雄", SkillTiming::Command, 1.0, "team_damage_bonus", 0.07, 1, 1, 0, ""}},
        {"运筹帷幄", {"运筹帷幄", SkillTiming::Active, 0.45, "strategy_damage", 1.35, 2, 1, 0, ""}},
        {"古之恶来", {"古之恶来", SkillTiming::Passive, 1.0, "team_damage_reduction", 0.05, 1, 1, 0, ""}},
        {"披坚执锐", {"披坚执锐", SkillTiming::Command, 1.0, "team_damage_reduction", 0.06, 1, 1, 0, ""}},
        {"虎痴", {"虎痴", SkillTiming::Passive, 1.0, "team_damage_bonus", 0.06, 1, 1, 0, ""}},
    };
    return skills;
}

std::vector<Skill> skills_for(const General& actor, SkillTiming timing) {
    std::vector<Skill> result;
    for (const auto& name : actor.skills) {
        auto found = skill_book().find(name);
        if (found != skill_book().end() && found->second.timing == timing) {
            result.push_back(found->second);
        }
    }
    return result;
}

std::string damage_label(DamageKind kind) {
    if (kind == DamageKind::Weapon) {
        return "兵刃";
    }
    if (kind == DamageKind::Strategy) {
        return "谋略";
    }
    if (kind == DamageKind::Deserter) {
        return "逃兵";
    }
    return "传递";
}

std::string timing_value(SkillTiming timing) {
    if (timing == SkillTiming::Passive) {
        return "passive";
    }
    if (timing == SkillTiming::Command) {
        return "command";
    }
    if (timing == SkillTiming::Pursuit) {
        return "pursuit";
    }
    return "active";
}

SkillTiming timing_from_value(const std::string& value) {
    if (value == "passive") {
        return SkillTiming::Passive;
    }
    if (value == "command") {
        return SkillTiming::Command;
    }
    if (value == "pursuit") {
        return SkillTiming::Pursuit;
    }
    return SkillTiming::Active;
}

double json_number_or(const Json& item, const std::string& key, double fallback) {
    if (!item.contains(key)) {
        return fallback;
    }
    return item.at(key).as_number();
}

int json_int_or(const Json& item, const std::string& key, int fallback) {
    if (!item.contains(key)) {
        return fallback;
    }
    return item.at(key).as_int();
}

std::string json_string_or(const Json& item, const std::string& key, const std::string& fallback) {
    if (!item.contains(key)) {
        return fallback;
    }
    return item.at(key).as_string();
}

Modifier load_modifier(const Json& item) {
    Modifier modifier;
    modifier.name = json_string_or(item, "name", json_string_or(item, "stat", "modifier"));
    modifier.stat = item.at("stat").as_string();
    modifier.value = item.at("value").as_number();
    modifier.expires_after_turn = json_int_or(item, "expires_after_turn", -1);
    modifier.source_actor = json_string_or(item, "source_actor", "");
    modifier.source_skill = json_string_or(item, "source_skill", "");
    if (item.contains("source_timing")) {
        modifier.source_timing = timing_from_value(item.at("source_timing").as_string());
        modifier.has_source_timing = true;
    }
    return modifier;
}

StatusEffect load_status(const Json& item) {
    StatusEffect status;
    status.name = item.at("name").as_string();
    status.remaining_rounds = json_int_or(item, "remaining_rounds", -1);
    status.stacks = json_int_or(item, "stacks", 1);
    status.max_stacks = json_int_or(item, "max_stacks", -1);
    status.source_actor = json_string_or(item, "source_actor", "");
    status.source_team = json_string_or(item, "source_team", "");
    return status;
}

Team load_team(const Json& data) {
    Team team;
    team.name = data.at("name").as_string();
    for (const auto& item : data.at("generals").as_array()) {
        General general;
        general.name = item.at("name").as_string();
        general.troops = item.at("troops").as_int();
        general.max_troops = json_int_or(item, "max_troops", general.troops);
        general.force = item.at("force").as_int();
        general.intellect = item.at("intellect").as_int();
        general.command = item.at("command").as_int();
        general.initiative = item.at("initiative").as_int();
        general.team = team.name;
        general.position = json_string_or(item, "position", "front");
        general.troop_type = json_string_or(item, "troop_type", "");
        general.faction = json_string_or(item, "faction", "");
        general.basic_target_weight = json_number_or(item, "basic_target_weight", 1.0);
        general.critical_chance = json_number_or(item, "critical_chance", 0.0);
        general.evasion_chance = json_number_or(item, "evasion_chance", 0.0);
        if (item.contains("skills")) {
            for (const auto& skill : item.at("skills").as_array()) {
                general.skills.push_back(skill.as_string());
            }
        }
        if (item.contains("modifiers")) {
            for (const auto& modifier : item.at("modifiers").as_array()) {
                general.modifiers.push_back(load_modifier(modifier));
            }
        }
        if (item.contains("statuses")) {
            for (const auto& status : item.at("statuses").as_array()) {
                general.statuses.push_back(load_status(status));
            }
        }
        team.generals.push_back(std::move(general));
    }
    return team;
}

} // namespace

double General::stat(const std::string& name) const {
    double base = 0.0;
    if (name == "force") {
        base = force;
    } else if (name == "intellect") {
        base = intellect;
    } else if (name == "command") {
        base = command;
    } else if (name == "initiative") {
        base = initiative;
    }
    for (const auto& modifier : modifiers) {
        if (modifier.stat == name) {
            base += modifier.value;
        }
    }
    return std::max(1.0, base);
}

double General::modifier_total(const std::string& name) const {
    double total = 0.0;
    for (const auto& modifier : modifiers) {
        if (modifier.stat == name) {
            total += modifier.value;
        }
    }
    return total;
}

int General::healable_max_troops() const {
    return std::max(0, max_troops - dead_troops);
}

bool General::has_status(const std::string& name) const {
    return status(name) != nullptr;
}

StatusEffect* General::status(const std::string& name) {
    for (auto& item : statuses) {
        if (item.name == name && item.stacks > 0) {
            return &item;
        }
    }
    return nullptr;
}

const StatusEffect* General::status(const std::string& name) const {
    for (const auto& item : statuses) {
        if (item.name == name && item.stacks > 0) {
            return &item;
        }
    }
    return nullptr;
}

void General::add_status(const StatusEffect& next) {
    StatusEffect* current = status(next.name);
    if (current == nullptr) {
        statuses.push_back(next);
        return;
    }
    current->stacks += next.stacks;
    int max_stacks = next.max_stacks >= 0 ? next.max_stacks : current->max_stacks;
    current->max_stacks = max_stacks;
    if (max_stacks >= 0) {
        current->stacks = std::min(current->stacks, max_stacks);
    }
    if (next.remaining_rounds >= 0) {
        current->remaining_rounds = current->remaining_rounds < 0 ? next.remaining_rounds : std::max(current->remaining_rounds, next.remaining_rounds);
    }
    if (!next.source_actor.empty()) {
        current->source_actor = next.source_actor;
    }
    if (!next.source_team.empty()) {
        current->source_team = next.source_team;
    }
    for (const auto& [key, value] : next.payload) {
        current->payload[key] = value;
    }
}

bool General::consume_status_stack(const std::string& name, int stacks) {
    for (auto it = statuses.begin(); it != statuses.end(); ++it) {
        if (it->name == name && it->stacks > 0) {
            it->stacks -= stacks;
            if (it->stacks <= 0) {
                statuses.erase(it);
            }
            return true;
        }
    }
    return false;
}

void General::expire_modifiers(int turn) {
    modifiers.erase(
        std::remove_if(modifiers.begin(), modifiers.end(), [turn](const Modifier& modifier) {
            return modifier.expires_after_turn >= 0 && modifier.expires_after_turn <= turn;
        }),
        modifiers.end());
}

void General::tick_status_durations() {
    for (auto& status : statuses) {
        if (status.remaining_rounds >= 0) {
            --status.remaining_rounds;
        }
    }
}

void General::purge_expired_statuses() {
    statuses.erase(
        std::remove_if(statuses.begin(), statuses.end(), [](const StatusEffect& status) {
            return status.remaining_rounds == 0;
        }),
        statuses.end());
}

void General::remove_command_effects_from(const std::string& source_actor) {
    modifiers.erase(
        std::remove_if(modifiers.begin(), modifiers.end(), [&](const Modifier& modifier) {
            return modifier.source_actor == source_actor && modifier.has_source_timing && modifier.source_timing == SkillTiming::Command;
        }),
        modifiers.end());
    statuses.erase(
        std::remove_if(statuses.begin(), statuses.end(), [&](const StatusEffect& status) {
            return status.source_actor == source_actor;
        }),
        statuses.end());
}

bool Team::defeated() const {
    return std::none_of(generals.begin(), generals.end(), [](const General& general) {
        return general.alive();
    });
}

int Team::total_troops() const {
    return std::accumulate(generals.begin(), generals.end(), 0, [](int total, const General& general) {
        return total + general.troops;
    });
}

std::vector<int> Team::alive_indexes() const {
    std::vector<int> indexes;
    for (int i = 0; i < static_cast<int>(generals.size()); ++i) {
        if (generals[i].alive()) {
            indexes.push_back(i);
        }
    }
    return indexes;
}

BattleSimulator::BattleSimulator(Battle battle, unsigned int seed)
    : battle_(std::move(battle)), rng_(seed) {}

BattleResult BattleSimulator::run() {
    apply_setup_phase();

    for (int round = 1; round <= battle_.max_rounds; ++round) {
        round_no_ = round;
        log_event("== 第 " + std::to_string(round) + " 回合 ==");

        auto order = action_order();
        for (General* actor : order) {
            if (!has_winner() && actor->alive()) {
                actor->purge_expired_statuses();
                take_turn(*actor);
            }
        }
        round_end();
        if (has_winner()) {
            break;
        }
    }

    return BattleResult{winner_name(), round_no_, battle_, log_};
}

std::vector<BattleResult> BattleSimulator::run_campaign(int max_battles) {
    std::vector<BattleResult> results;
    for (int battle_index = 1; battle_index <= max_battles; ++battle_index) {
        reset_transient_state();
        BattleResult result = run();
        results.push_back(result);
        settle_post_battle(result.winner_name);
        if (result.winner_name != "平局") {
            break;
        }
        if (battle_index == max_battles) {
            for (General* general : all_generals()) {
                general->dead_troops += general->troops;
                general->troops = 0;
            }
            log_event("连续平局至上限，双方兵疲意阻");
        }
    }
    return results;
}

Team& BattleSimulator::enemies_of(General& actor) {
    return actor.team == battle_.team_a.name ? battle_.team_b : battle_.team_a;
}

Team& BattleSimulator::allies_of(General& actor) {
    return actor.team == battle_.team_a.name ? battle_.team_a : battle_.team_b;
}

void BattleSimulator::log_event(const std::string& message) {
    log_.push_back(message);
}

int BattleSimulator::deal_damage(General& actor, General& target, double power, DamageKind kind, const std::string& source) {
    if (!actor.alive() || !target.alive()) {
        return 0;
    }
    const bool bypass_evasion = kind == DamageKind::Deserter || actor.has_status(kSureHit);
    if (!bypass_evasion && roll(combined_evasion(target))) {
        log_event(target.name + " 规避了 " + actor.name + " 的 " + source);
        return 0;
    }

    int damage = raw_damage(actor, target, power, kind, source);
    if (kind != DamageKind::Deserter && kind != DamageKind::Transfer && !actor.has_status(kPierceResist)) {
        if (StatusEffect* resist = target.status(kResist)) {
            double reduction = 0.70;
            auto found = resist->payload.find("damage_reduction");
            if (found != resist->payload.end()) {
                reduction = found->second;
            }
            target.consume_status_stack(kResist);
            damage = static_cast<int>(damage * std::max(0.0, 1.0 - reduction));
            log_event(target.name + " 消耗 1 层抵御");
        }
    }

    damage = std::max(1, std::min(target.troops, damage));
    target.troops -= damage;
    int dead = static_cast<int>(damage * 0.20);
    target.dead_troops += dead;
    target.wounded_troops += damage - dead;

    std::ostringstream line;
    line << actor.name << " 使用 " << source << " 对 " << target.name << " 造成 " << damage << " "
         << damage_label(kind) << "伤害";
    log_event(line.str());
    if (!target.alive()) {
        on_general_defeated(target);
    }
    return damage;
}

int BattleSimulator::heal(General& actor, General& target, double power, const std::string& source) {
    int missing = target.healable_max_troops() - target.troops;
    if (!actor.alive() || !target.alive() || missing <= 0) {
        return 0;
    }
    double bonus = 1.0 + actor.modifier_total("healing_dealt_bonus") + target.modifier_total("healing_taken_bonus");
    if (target.has_status(kStarve)) {
        bonus *= 0.30;
    }
    int amount = static_cast<int>((220.0 + actor.stat("intellect") * 2.0) * power * troop_damage_factor(actor) * std::max(0.0, bonus));
    amount = std::min(missing, std::max(0, amount));
    target.troops += amount;
    target.wounded_troops = std::max(0, target.wounded_troops - amount);

    std::ostringstream line;
    line << actor.name << " 使用 " << source << " 恢复 " << target.name << " " << amount << " 兵力";
    log_event(line.str());
    return amount;
}

void BattleSimulator::take_turn(General& actor) {
    if (actor.has_status(kStun)) {
        log_event(actor.name + " 处于震慑，跳过行动");
        return;
    }

    if (actor.has_status(kSilence)) {
        actor.preparations.clear();
        log_event(actor.name + " 处于技穷，跳过主动战法");
    } else {
        for (const Skill& skill : skills_for(actor, SkillTiming::Active)) {
            try_active_skill(actor, skill);
            if (has_winner() || !actor.alive()) {
                return;
            }
        }
    }

    int basic_damage = try_basic_attack(actor);
    if (basic_damage <= 0) {
        return;
    }

    for (const Skill& skill : skills_for(actor, SkillTiming::Pursuit)) {
        try_cast(skill, actor);
        if (has_winner()) {
            return;
        }
    }
}

bool BattleSimulator::try_active_skill(General& actor, const Skill& skill) {
    if (skill.prepare_rounds <= 0) {
        return try_cast(skill, actor);
    }
    int progress = actor.preparations[skill.name];
    if (progress <= 0) {
        if (!roll(skill.chance + actor.modifier_total("active_chance_bonus"))) {
            actor.preparations.erase(skill.name);
            return false;
        }
        actor.preparations[skill.name] = 1;
        log_event(actor.name + " 开始准备 " + skill.name);
        return true;
    }
    ++progress;
    if (progress < skill.prepare_rounds + 1) {
        actor.preparations[skill.name] = progress;
        log_event(actor.name + " 继续准备 " + skill.name);
        return true;
    }
    actor.preparations.erase(skill.name);
    return try_cast(skill, actor);
}

int BattleSimulator::try_basic_attack(General& actor) {
    if (actor.has_status(kDisarm)) {
        log_event(actor.name + " 处于缴械，跳过普攻与追击");
        return 0;
    }
    General* target = pick_basic_attack_target(actor);
    if (target == nullptr) {
        return 0;
    }
    int damage = deal_damage(actor, *target, 1.0, DamageKind::Weapon, "普通攻击");
    if (damage > 0 && target->alive()) {
        try_counterattack(*target, actor);
    }
    return damage;
}

void BattleSimulator::try_counterattack(General& defender, General& attacker) {
    const StatusEffect* counter = defender.status("反击");
    double chance = defender.modifier_total("counter_chance");
    double power = defender.modifier_total("counter_power");
    if (power <= 0.0) {
        power = 0.72;
    }
    if (counter != nullptr) {
        auto chance_it = counter->payload.find("chance");
        if (chance_it != counter->payload.end()) {
            chance = std::max(chance, chance_it->second);
        } else {
            chance = std::max(chance, 1.0);
        }
        auto power_it = counter->payload.find("power");
        if (power_it != counter->payload.end()) {
            power = power_it->second;
        }
    }
    if (chance > 0.0 && roll(chance)) {
        deal_damage(defender, attacker, power, DamageKind::Weapon, "反击");
    }
}

void BattleSimulator::apply_setup_phase() {
    round_no_ = 0;
    apply_setup_skills(SkillTiming::Passive);

    std::vector<General*> actors = all_generals();
    std::sort(actors.begin(), actors.end(), [](const General* left, const General* right) {
        return left->stat("initiative") > right->stat("initiative");
    });
    for (General* actor : actors) {
        if (!actor->alive()) {
            continue;
        }
        for (const Skill& skill : skills_for(*actor, SkillTiming::Command)) {
            try_cast(skill, *actor);
        }
    }
}

void BattleSimulator::apply_setup_skills(SkillTiming timing) {
    for (General* actor : all_generals()) {
        if (!actor->alive()) {
            continue;
        }
        for (const Skill& skill : skills_for(*actor, timing)) {
            try_cast(skill, *actor);
        }
    }
}

void BattleSimulator::expire_temporary_effects() {
    for (General* actor : all_generals()) {
        actor->expire_modifiers(round_no_);
    }
}

void BattleSimulator::round_end() {
    for (General* actor : all_generals()) {
        if (!actor->alive()) {
            continue;
        }
        const StatusEffect* burn = actor->status("焚烧");
        const StatusEffect* poison = actor->status("中毒");
        const StatusEffect* dots[] = {burn, poison};
        for (const StatusEffect* dot : dots) {
            if (dot == nullptr) {
                continue;
            }
            General* source = find_general(dot->source_actor);
            General& attacker = (source != nullptr && source->alive()) ? *source : *actor;
            double power = 0.60 * std::max(1, dot->stacks);
            auto found = dot->payload.find("power");
            if (found != dot->payload.end()) {
                power = found->second * std::max(1, dot->stacks);
            }
            deal_damage(attacker, *actor, power, DamageKind::Strategy, dot->name);
        }
    }
    for (General* actor : all_generals()) {
        actor->tick_status_durations();
        actor->expire_modifiers(round_no_);
        if (!actor->alive()) {
            on_general_defeated(*actor);
        }
    }
}

void BattleSimulator::reset_transient_state() {
    round_no_ = 0;
    log_.clear();
    for (General* general : all_generals()) {
        general->statuses.clear();
        general->preparations.clear();
        general->damage_bonus = 0.0;
        general->damage_reduction = 0.0;
        general->modifiers.erase(
            std::remove_if(general->modifiers.begin(), general->modifiers.end(), [](const Modifier& modifier) {
                return !modifier.source_skill.empty() || modifier.expires_after_turn >= 0;
            }),
            general->modifiers.end());
    }
}

void BattleSimulator::settle_post_battle(const std::string& winner) {
    for (General* general : all_generals()) {
        if (general->wounded_troops <= 0) {
            continue;
        }
        double conversion = 0.25;
        if (winner != "平局") {
            conversion = general->team == winner ? 0.10 : 0.75;
        }
        int newly_dead = static_cast<int>(general->wounded_troops * conversion);
        general->dead_troops += newly_dead;
        general->wounded_troops = std::max(0, general->wounded_troops - newly_dead);
        int recover = std::min(general->wounded_troops, std::max(0, general->healable_max_troops() - general->troops));
        general->troops += recover;
        general->wounded_troops -= recover;
    }
}

std::vector<General*> BattleSimulator::action_order() {
    std::vector<General*> left;
    std::vector<General*> right;
    for (General& actor : battle_.team_a.generals) {
        if (actor.alive()) {
            left.push_back(&actor);
        }
    }
    for (General& actor : battle_.team_b.generals) {
        if (actor.alive()) {
            right.push_back(&actor);
        }
    }
    auto by_initiative = [](const General* a, const General* b) {
        return a->stat("initiative") > b->stat("initiative");
    };
    std::sort(left.begin(), left.end(), by_initiative);
    std::sort(right.begin(), right.end(), by_initiative);

    std::vector<General*> order;
    std::size_t ia = 0;
    std::size_t ib = 0;
    while (ia < left.size() && ib < right.size()) {
        double diff = left[ia]->stat("initiative") - right[ib]->stat("initiative");
        bool left_first;
        if (std::abs(diff) > 70.0) {
            left_first = diff > 0.0;
        } else {
            double lw = std::max(1.0, left[ia]->stat("initiative"));
            double rw = std::max(1.0, right[ib]->stat("initiative"));
            left_first = roll(lw / (lw + rw));
        }
        if (left_first) {
            order.push_back(left[ia++]);
        } else {
            order.push_back(right[ib++]);
        }
    }
    while (ia < left.size()) {
        order.push_back(left[ia++]);
    }
    while (ib < right.size()) {
        order.push_back(right[ib++]);
    }
    return order;
}

General* BattleSimulator::pick_basic_attack_target(General& actor) {
    if (actor.has_status(kConfusion)) {
        std::vector<General*> candidates;
        for (General* general : all_generals()) {
            if (general->alive() && general != &actor) {
                candidates.push_back(general);
            }
        }
        auto picked = weighted_sample(candidates, 1);
        return picked.empty() ? nullptr : picked.front();
    }
    if (const StatusEffect* taunt = actor.status(kTaunt)) {
        for (General& enemy : enemies_of(actor).generals) {
            if (enemy.alive() && enemy.name == taunt->source_actor) {
                return &enemy;
            }
        }
    }
    auto picked = pick_targets(enemies_of(actor), 1);
    return picked.empty() ? nullptr : picked.front();
}

bool BattleSimulator::try_cast(const Skill& skill, General& actor) {
    if (!actor.alive() || !roll(skill.chance + actor.modifier_total(timing_value(skill.timing) + "_chance_bonus"))) {
        return false;
    }

    if (skill.effect == "weapon_damage" || skill.effect == "strategy_damage") {
        DamageKind kind = skill.effect == "weapon_damage" ? DamageKind::Weapon : DamageKind::Strategy;
        for (General* target : pick_damage_targets(actor, skill.targets)) {
            deal_damage(actor, *target, skill.power, kind, skill.name);
        }
        return true;
    }

    if (skill.effect == "heal") {
        Team& allies = allies_of(actor);
        std::vector<General*> wounded;
        for (General& ally : allies.generals) {
            if (ally.alive() && ally.troops < ally.healable_max_troops()) {
                wounded.push_back(&ally);
            }
        }
        std::sort(wounded.begin(), wounded.end(), [](const General* l, const General* r) {
            return static_cast<double>(l->troops) / l->max_troops < static_cast<double>(r->troops) / r->max_troops;
        });
        int count = std::min(skill.targets, static_cast<int>(wounded.size()));
        for (int i = 0; i < count; ++i) {
            heal(actor, *wounded[i], skill.power, skill.name);
        }
        return count > 0;
    }

    if (skill.effect == "reduce_enemy_command") {
        for (General* target : pick_targets(enemies_of(actor), skill.targets)) {
            double amount = -std::max(8.0, actor.stat("force") * skill.power * 0.12);
            target->modifiers.push_back({skill.name, "command", amount, round_no_ + skill.duration, actor.name, skill.name, skill.timing, true});
            std::ostringstream line;
            line << actor.name << " 发动 " << skill.name << "，" << target->name << " 统率 " << static_cast<int>(amount);
            log_event(line.str());
        }
        return true;
    }

    if (skill.effect == "team_damage_reduction") {
        for (General& ally : allies_of(actor).generals) {
            if (ally.alive()) {
                ally.modifiers.push_back({skill.name, "damage_taken_reduction", skill.power, -1, actor.name, skill.name, skill.timing, true});
            }
        }
        log_event(actor.name + " 发动 " + skill.name + "，己方获得减伤 " + std::to_string(static_cast<int>(skill.power * 100)) + "%");
        return true;
    }

    if (skill.effect == "team_damage_bonus") {
        for (General& ally : allies_of(actor).generals) {
            if (ally.alive()) {
                ally.modifiers.push_back({skill.name, "damage_dealt_bonus", skill.power, -1, actor.name, skill.name, skill.timing, true});
            }
        }
        log_event(actor.name + " 发动 " + skill.name + "，己方增伤 " + std::to_string(static_cast<int>(skill.power * 100)) + "%");
        return true;
    }

    return false;
}

std::vector<General*> BattleSimulator::pick_targets(Team& team, int count) {
    std::vector<General*> alive;
    for (General& general : team.generals) {
        if (general.alive()) {
            alive.push_back(&general);
        }
    }
    return weighted_sample(alive, count);
}

std::vector<General*> BattleSimulator::pick_damage_targets(General& actor, int count) {
    if (actor.has_status(kConfusion)) {
        std::vector<General*> candidates;
        for (General* general : all_generals()) {
            if (general->alive() && general != &actor) {
                candidates.push_back(general);
            }
        }
        return weighted_sample(candidates, count);
    }
    return pick_targets(enemies_of(actor), count);
}

std::vector<General*> BattleSimulator::weighted_sample(std::vector<General*> candidates, int count) {
    std::vector<General*> picked;
    while (!candidates.empty() && static_cast<int>(picked.size()) < count) {
        std::vector<double> weights;
        double total = 0.0;
        for (General* general : candidates) {
            double ratio = general->max_troops > 0 ? static_cast<double>(general->troops) / general->max_troops : 0.0;
            double weight = std::max(0.0, general->basic_target_weight) * (0.5 + 0.5 * ratio);
            weights.push_back(weight);
            total += weight;
        }
        int selected = static_cast<int>(candidates.size()) - 1;
        if (total <= 0.0) {
            std::uniform_int_distribution<int> dist(0, static_cast<int>(candidates.size()) - 1);
            selected = dist(rng_);
        } else {
            std::uniform_real_distribution<double> dist(0.0, total);
            double rolled = dist(rng_);
            double upto = 0.0;
            for (int i = 0; i < static_cast<int>(candidates.size()); ++i) {
                upto += weights[i];
                if (rolled <= upto) {
                    selected = i;
                    break;
                }
            }
        }
        picked.push_back(candidates[selected]);
        candidates.erase(candidates.begin() + selected);
    }
    return picked;
}

std::vector<General*> BattleSimulator::all_generals() {
    std::vector<General*> result;
    for (General& actor : battle_.team_a.generals) {
        result.push_back(&actor);
    }
    for (General& actor : battle_.team_b.generals) {
        result.push_back(&actor);
    }
    return result;
}

General* BattleSimulator::find_general(const std::string& name) {
    if (name.empty()) {
        return nullptr;
    }
    for (General* general : all_generals()) {
        if (general->name == name) {
            return general;
        }
    }
    return nullptr;
}

void BattleSimulator::on_general_defeated(General& defeated) {
    for (General* general : all_generals()) {
        general->remove_command_effects_from(defeated.name);
    }
}

int BattleSimulator::raw_damage(General& actor, General& target, double power, DamageKind kind, const std::string& source) {
    if (kind == DamageKind::Deserter) {
        return static_cast<int>(std::max(1.0, actor.stat("force") * power));
    }
    if (kind == DamageKind::Transfer) {
        return static_cast<int>(std::max(0.0, power));
    }

    double base = 1.0;
    if (kind == DamageKind::Weapon) {
        base = 360.0 + actor.stat("force") - target.stat("command");
    } else {
        base = 360.0 + actor.stat("intellect") - 0.5 * target.stat("command") - 0.5 * target.stat("intellect");
    }
    std::string timing = source_timing_name(source);
    double damage = std::max(1.0, base) * power * damage_dealt_multiplier(actor, kind, timing)
        * damage_taken_multiplier(target, kind, timing) * troop_damage_factor(actor) * critical_multiplier(actor, kind);
    return static_cast<int>(damage);
}

double BattleSimulator::damage_dealt_multiplier(const General& actor, DamageKind kind, const std::string& timing) const {
    double bonus = actor.damage_bonus + actor.modifier_total("damage_dealt_bonus");
    double reduction = actor.modifier_total("damage_dealt_reduction");
    if (actor.has_status(kWeaken)) {
        reduction += 0.70;
    }
    double result = std::max(0.30, 1.0 + bonus - reduction);
    std::string kind_key = kind == DamageKind::Weapon ? "weapon" : "strategy";
    for (const std::string& stat : {kind_key + "_damage_bonus", timing + "_damage_bonus"}) {
        double value = actor.modifier_total(stat);
        if (value != 0.0) {
            result *= std::max(0.05, 1.0 + value);
        }
    }
    return result;
}

double BattleSimulator::damage_taken_multiplier(const General& target, DamageKind kind, const std::string& timing) const {
    std::string kind_key = kind == DamageKind::Weapon ? "weapon" : "strategy";
    std::vector<double> reductions = {target.damage_reduction};
    std::vector<double> increases;
    for (const std::string& stat : {"damage_taken_reduction", kind_key + "_damage_taken_reduction", timing + "_damage_taken_reduction"}) {
        auto values = modifier_values(target, stat);
        reductions.insert(reductions.end(), values.begin(), values.end());
    }
    for (const std::string& stat : {"damage_taken_increase", kind_key + "_damage_taken_increase", timing + "_damage_taken_increase"}) {
        auto values = modifier_values(target, stat);
        increases.insert(increases.end(), values.begin(), values.end());
    }
    return (1.0 - combine_rates(reductions)) * (1.0 + combine_rates(increases));
}

double BattleSimulator::combined_evasion(const General& target) const {
    std::vector<double> rates = {target.evasion_chance};
    auto values = modifier_values(target, "evasion_chance");
    rates.insert(rates.end(), values.begin(), values.end());
    for (const auto& status : target.statuses) {
        auto found = status.payload.find("evasion_chance");
        if (found != status.payload.end()) {
            rates.push_back(found->second);
        }
    }
    return combine_rates(rates);
}

double BattleSimulator::critical_multiplier(const General& actor, DamageKind kind) {
    std::string kind_key = kind == DamageKind::Weapon ? "weapon" : "strategy";
    double chance = actor.critical_chance + actor.modifier_total("critical_chance") + actor.modifier_total(kind_key + "_critical_chance");
    if (chance <= 0.0 || !roll(chance)) {
        return 1.0;
    }
    return 1.5 + actor.modifier_total("critical_damage_bonus") + actor.modifier_total(kind_key + "_critical_damage_bonus");
}

double BattleSimulator::troop_damage_factor(const General& actor) const {
    if (actor.max_troops <= 0) {
        return 1.0;
    }
    return std::max(0.35, 0.5 + 0.5 * static_cast<double>(actor.troops) / actor.max_troops);
}

std::string BattleSimulator::source_timing_name(const std::string& source) const {
    if (source == "普通攻击") {
        return "basic";
    }
    if (source == "反击") {
        return "counter";
    }
    for (const General& actor : battle_.team_a.generals) {
        for (const Skill& skill : skills_for(actor, SkillTiming::Active)) {
            if (skill.name == source) {
                return "active";
            }
        }
        for (const Skill& skill : skills_for(actor, SkillTiming::Pursuit)) {
            if (skill.name == source) {
                return "pursuit";
            }
        }
    }
    for (const General& actor : battle_.team_b.generals) {
        for (const Skill& skill : skills_for(actor, SkillTiming::Active)) {
            if (skill.name == source) {
                return "active";
            }
        }
        for (const Skill& skill : skills_for(actor, SkillTiming::Pursuit)) {
            if (skill.name == source) {
                return "pursuit";
            }
        }
    }
    return "damage";
}

std::vector<double> BattleSimulator::modifier_values(const General& actor, const std::string& stat) const {
    std::vector<double> values;
    for (const auto& modifier : actor.modifiers) {
        if (modifier.stat == stat && modifier.value > 0.0) {
            values.push_back(modifier.value);
        }
    }
    return values;
}

double BattleSimulator::combine_rates(const std::vector<double>& rates) const {
    double remaining = 1.0;
    for (double rate : rates) {
        remaining *= 1.0 - std::max(0.0, std::min(1.0, rate));
    }
    return 1.0 - remaining;
}

bool BattleSimulator::roll(double chance) {
    std::uniform_real_distribution<double> dist(0.0, 1.0);
    return dist(rng_) < std::max(0.0, std::min(1.0, chance));
}

bool BattleSimulator::has_winner() const {
    return battle_.team_a.defeated() || battle_.team_b.defeated();
}

std::string BattleSimulator::winner_name() const {
    const Team& a = battle_.team_a;
    const Team& b = battle_.team_b;
    if (a.defeated() && b.defeated()) {
        return "平局";
    }
    if (b.defeated()) {
        return a.name;
    }
    if (a.defeated()) {
        return b.name;
    }
    return "平局";
}

Battle load_battle_json(const Json& root) {
    Battle battle;
    battle.team_a = load_team(root.at("team_a"));
    battle.team_b = load_team(root.at("team_b"));
    battle.max_rounds = root.contains("max_rounds") ? root.at("max_rounds").as_int() : 8;
    return battle;
}

Battle load_battle_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("cannot open config: " + path);
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    return load_battle_json(Json::parse(buffer.str()));
}

} // namespace sanmou
