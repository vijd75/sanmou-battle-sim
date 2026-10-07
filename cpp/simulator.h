#pragma once

#include "json.h"
#include "models.h"

#include <random>
#include <string>

namespace sanmou {

struct Skill {
    std::string name;
    SkillTiming timing = SkillTiming::Active;
    double chance = 1.0;
    std::string effect;
    double power = 1.0;
    int targets = 1;
    int duration = 1;
    int prepare_rounds = 0;
    std::string status_name;
};

class BattleSimulator {
public:
    BattleSimulator(Battle battle, unsigned int seed);

    BattleResult run();
    std::vector<BattleResult> run_campaign(int max_battles = 8);

private:
    Team& enemies_of(General& actor);
    Team& allies_of(General& actor);
    void log_event(const std::string& message);
    int deal_damage(General& actor, General& target, double power, DamageKind kind, const std::string& source);
    int heal(General& actor, General& target, double power, const std::string& source);
    void take_turn(General& actor);
    bool try_active_skill(General& actor, const Skill& skill);
    int try_basic_attack(General& actor);
    void try_counterattack(General& defender, General& attacker);
    void apply_setup_skills(SkillTiming timing);
    void apply_setup_phase();
    void expire_temporary_effects();
    void round_end();
    void reset_transient_state();
    void settle_post_battle(const std::string& winner_name);
    std::vector<General*> action_order();
    General* pick_basic_attack_target(General& actor);
    bool try_cast(const Skill& skill, General& actor);
    std::vector<General*> pick_targets(Team& team, int count);
    std::vector<General*> pick_damage_targets(General& actor, int count);
    std::vector<General*> weighted_sample(std::vector<General*> candidates, int count);
    std::vector<General*> all_generals();
    General* find_general(const std::string& name);
    void on_general_defeated(General& defeated);
    int raw_damage(General& actor, General& target, double power, DamageKind kind, const std::string& source);
    double damage_dealt_multiplier(const General& actor, DamageKind kind, const std::string& timing) const;
    double damage_taken_multiplier(const General& target, DamageKind kind, const std::string& timing) const;
    double combined_evasion(const General& target) const;
    double critical_multiplier(const General& actor, DamageKind kind);
    double troop_damage_factor(const General& actor) const;
    std::string source_timing_name(const std::string& source) const;
    std::vector<double> modifier_values(const General& actor, const std::string& stat) const;
    double combine_rates(const std::vector<double>& rates) const;
    bool roll(double chance);
    bool has_winner() const;
    std::string winner_name() const;

    Battle battle_;
    std::mt19937 rng_;
    int round_no_ = 0;
    std::vector<std::string> log_;
};

Battle load_battle_json(const Json& root);
Battle load_battle_file(const std::string& path);

} // namespace sanmou
