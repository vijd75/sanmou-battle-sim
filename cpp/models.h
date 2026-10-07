#pragma once

#include <string>
#include <unordered_map>
#include <vector>

namespace sanmou {

enum class DamageKind {
    Weapon,
    Strategy,
    Deserter,
    Transfer,
};

enum class SkillTiming {
    Passive,
    Command,
    Active,
    Pursuit,
};

struct Modifier {
    std::string name;
    std::string stat;
    double value = 0.0;
    int expires_after_turn = -1;
    std::string source_actor;
    std::string source_skill;
    SkillTiming source_timing = SkillTiming::Active;
    bool has_source_timing = false;
};

struct StatusEffect {
    std::string name;
    int remaining_rounds = -1;
    int stacks = 1;
    int max_stacks = -1;
    std::string source_actor;
    std::string source_team;
    std::unordered_map<std::string, double> payload;
};

struct General {
    std::string name;
    int troops = 0;
    int max_troops = 0;
    int force = 0;
    int intellect = 0;
    int command = 0;
    int initiative = 0;
    std::vector<std::string> skills;
    std::string team;
    std::string position = "front";
    std::string troop_type;
    std::string faction;
    double basic_target_weight = 1.0;
    std::vector<Modifier> modifiers;
    std::vector<StatusEffect> statuses;
    std::unordered_map<std::string, int> preparations;
    int wounded_troops = 0;
    int dead_troops = 0;
    double damage_bonus = 0.0;
    double damage_reduction = 0.0;
    double critical_chance = 0.0;
    double evasion_chance = 0.0;

    bool alive() const {
        return troops > 0;
    }

    double stat(const std::string& name) const;
    double modifier_total(const std::string& name) const;
    int healable_max_troops() const;
    bool has_status(const std::string& name) const;
    StatusEffect* status(const std::string& name);
    const StatusEffect* status(const std::string& name) const;
    void add_status(const StatusEffect& status);
    bool consume_status_stack(const std::string& name, int stacks = 1);
    void expire_modifiers(int turn);
    void tick_status_durations();
    void purge_expired_statuses();
    void remove_command_effects_from(const std::string& source_actor);
};

struct Team {
    std::string name;
    std::vector<General> generals;

    bool defeated() const;
    int total_troops() const;
    std::vector<int> alive_indexes() const;
};

struct Battle {
    Team team_a;
    Team team_b;
    int max_rounds = 8;
};

struct BattleResult {
    std::string winner_name;
    int rounds = 0;
    Battle battle;
    std::vector<std::string> log;
};

} // namespace sanmou
