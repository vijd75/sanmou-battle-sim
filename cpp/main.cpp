#include "simulator.h"

#include <chrono>
#include <iostream>
#include <string>
#include <utility>

#ifdef _WIN32
#include <windows.h>
#endif

namespace {

unsigned int seed_from_args(int argc, char** argv) {
    for (int i = 2; i + 1 < argc; ++i) {
        if (std::string(argv[i]) == "--seed") {
            return static_cast<unsigned int>(std::stoul(argv[i + 1]));
        }
    }
    return static_cast<unsigned int>(
        std::chrono::high_resolution_clock::now().time_since_epoch().count());
}

bool has_arg(int argc, char** argv, const std::string& name) {
    for (int i = 2; i < argc; ++i) {
        if (std::string(argv[i]) == name) {
            return true;
        }
    }
    return false;
}

int int_arg(int argc, char** argv, const std::string& name, int fallback) {
    for (int i = 2; i + 1 < argc; ++i) {
        if (std::string(argv[i]) == name) {
            return std::stoi(argv[i + 1]);
        }
    }
    return fallback;
}

void print_result(const sanmou::BattleResult& result) {
    std::cout << "胜者: " << result.winner_name << "\n";
    std::cout << "回合数: " << result.rounds << "\n\n";
    std::cout << "剩余兵力:\n";
    for (const sanmou::Team* team : {&result.battle.team_a, &result.battle.team_b}) {
        std::cout << "- " << team->name << ": " << team->total_troops() << "\n";
        for (const sanmou::General& general : team->generals) {
            std::cout << "  - " << general.name << ": " << general.troops << "/" << general.max_troops
                      << " 伤兵" << general.wounded_troops << " 死兵" << general.dead_troops
                      << " (" << (general.alive() ? "存活" : "阵亡") << ")\n";
        }
    }
    std::cout << "\n战报:\n";
    for (const std::string& line : result.log) {
        std::cout << line << "\n";
    }
}

} // namespace

int main(int argc, char** argv) {
#ifdef _WIN32
    SetConsoleOutputCP(CP_UTF8);
#endif

    if (argc < 2) {
        std::cerr << "用法: sanmou_sim_cpp <battle.json> [--seed 7] [--campaign] [--max-battles 8]\n";
        return 2;
    }

    try {
        sanmou::Battle battle = sanmou::load_battle_file(argv[1]);
        sanmou::BattleSimulator simulator(std::move(battle), seed_from_args(argc, argv));
        if (has_arg(argc, argv, "--campaign")) {
            auto results = simulator.run_campaign(int_arg(argc, argv, "--max-battles", 8));
            for (int i = 0; i < static_cast<int>(results.size()); ++i) {
                std::cout << "第 " << (i + 1) << " 局\n";
                print_result(results[i]);
                if (i + 1 < static_cast<int>(results.size())) {
                    std::cout << "\n";
                }
            }
        } else {
            print_result(simulator.run());
        }
    } catch (const std::exception& error) {
        std::cerr << "错误: " << error.what() << "\n";
        return 1;
    }

    return 0;
}
