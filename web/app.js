const state = {
  generals: [],
  skills: [],
  teams: [
    { name: "我方", slots: [] },
    { name: "敌方", slots: [] },
  ],
};

const SKILL_TYPE_ORDER = ["指挥", "被动", "追击", "主动"];
const FREE_ATTRIBUTE_POINTS = 50;
const STAT_KEYS = ["force", "intellect", "command", "initiative"];
const FORMATIONS = [
  {
    id: "yizi",
    name: "一字阵",
    positions: ["front", "front", "front"],
    targetWeights: [0.33, 0.34, 0.33],
    effects: [{ lane: "front", stat: "damage_taken_reduction", value: 0.08, text: "前排受到伤害降低8%" }],
  },
  {
    id: "jixing",
    name: "箕形阵",
    positions: ["front", "back", "back"],
    targetWeights: [0.60, 0.20, 0.20],
    effects: [
      { lane: "front", stat: "damage_taken_reduction", value: 0.06, text: "前排受到伤害降低6%" },
      { lane: "back", stat: "damage_dealt_bonus", value: 0.12, text: "后排造成伤害提升12%" },
    ],
  },
  {
    id: "yanxing",
    name: "雁形阵",
    positions: ["front", "front", "back"],
    targetWeights: [0.40, 0.40, 0.20],
    effects: [
      { lane: "front", stat: "command", value: 20, text: "前排统率增加20点" },
      { lane: "back", stat: "damage_dealt_bonus", value: 0.15, text: "后排造成伤害提升15%" },
    ],
  },
  {
    id: "fangyuan",
    name: "方圆阵",
    positions: ["front", "front", "back"],
    targetWeights: [0.40, 0.40, 0.20],
    effects: [
      { lane: "front", stat: "damage_taken_reduction", value: 0.05, text: "前排受到伤害降低5%" },
      { lane: "back", stat: "combo_chance", value: 0.40, text: "后排连击率增加40%" },
    ],
  },
  {
    id: "zhuixing",
    name: "锥形阵",
    positions: ["front", "back", "back"],
    targetWeights: [0.60, 0.20, 0.20],
    effects: [
      { lane: "front", stat: "damage_dealt_bonus", value: 0.16, text: "前排造成伤害增加16%" },
      { lane: "back", stat: "damage_taken_reduction", value: 0.05, text: "后排受到伤害降低5%" },
    ],
  },
  {
    id: "yulin",
    name: "鱼鳞阵",
    positions: ["front", "back", "back"],
    targetWeights: [0.60, 0.20, 0.20],
    effects: [
      { lane: "front", stat: "evasion_chance", value: 0.12, text: "前排规避率提升12%" },
      { lane: "back", stat: "critical_chance", value: 0.08, text: "后排会心和奇谋几率增加8%" },
    ],
  },
  {
    id: "gouxing",
    name: "钩形阵",
    positions: ["back", "back", "front"],
    targetWeights: [0.20, 0.20, 0.60],
    effects: [
      { lane: "front", stat: "damage_taken_reduction", value: 0.08, text: "前排受到伤害降低8%" },
      { lane: "back", stat: "combo_chance", value: 0.25, text: "后排连击率提升25%" },
    ],
  },
  {
    id: "yanyue",
    name: "偃月阵",
    positions: ["front", "back", "front"],
    targetWeights: [0.40, 0.20, 0.40],
    effects: [
      { lane: "front", stat: "damage_dealt_bonus", value: 0.14, text: "前排造成伤害提升14%" },
      { lane: "back", stat: "damage_taken_reduction", value: 0.05, text: "后排受到伤害降低5%" },
    ],
  },
];

const teamsRoot = document.querySelector("#teams");
const teamTemplate = document.querySelector("#teamTemplate");
const slotTemplate = document.querySelector("#slotTemplate");
const levelInput = document.querySelector("#levelInput");
const troopsInput = document.querySelector("#troopsInput");
const seedInput = document.querySelector("#seedInput");
const jsonOutput = document.querySelector("#jsonOutput");
const dataStatus = document.querySelector("#dataStatus");
const copyButton = document.querySelector("#copyButton");
const downloadButton = document.querySelector("#downloadButton");
const simulateButton = document.querySelector("#simulateButton");
const toggleConfigButton = document.querySelector("#toggleConfigButton");
const resetButton = document.querySelector("#resetButton");
const workspace = document.querySelector("#workspace");
const configPreview = document.querySelector("#configPreview");
const battleResult = document.querySelector("#battleResult");
const battleSummary = document.querySelector("#battleSummary");
const battleStats = document.querySelector("#battleStats");
const battleLog = document.querySelector("#battleLog");
const battleRoundNav = document.querySelector("#battleRoundNav");
const generalStateTooltip = document.querySelector("#generalStateTooltip");
const skillDescriptionDialog = document.querySelector("#skillDescriptionDialog");
const skillDescriptionTitle = document.querySelector("#skillDescriptionTitle");
const skillDescriptionMeta = document.querySelector("#skillDescriptionMeta");
const skillDescriptionText = document.querySelector("#skillDescriptionText");
let activeSkillDescriptionAnchor = null;
let currentLogEntries = [];
let currentLogSections = [];

boot();

async function boot() {
  try {
    const [generalsData, skillsData] = await Promise.all([
      fetch("../data/generals.json").then((response) => response.json()),
      fetch("../data/skills.json").then((response) => response.json()),
    ]);
    state.generals = generalsData.generals ?? [];
    state.skills = skillsData.skills ?? [];
    resetTeams();
    render();
    setStatus(`${state.generals.length} 名武将，${state.skills.length} 个战法`, false);
  } catch (error) {
    setStatus("读取失败，请通过本地服务打开 web/index.html", true);
    jsonOutput.textContent = String(error);
  }
}

function resetTeams() {
  const defaults = ["刘备", "关羽", "张飞", "曹操", "典韦", "许褚"];
  state.teams = state.teams.map((team, teamIndex) => ({
    name: teamIndex === 0 ? "我方" : "敌方",
    formationId: "jixing",
    slots: [0, 1, 2].map((slotIndex) => {
      const general = findGeneral(defaults[teamIndex * 3 + slotIndex]) ?? state.generals[teamIndex * 3 + slotIndex];
      return {
        generalName: general?.name ?? "",
        generalQuery: "",
        position: formationById("jixing").positions[slotIndex],
        allocation: { force: 0, intellect: 0, command: 0, initiative: 0 },
        skillQueries: ["", ""],
        extraSkills: ["", ""],
      };
    }),
  }));
}

function render() {
  hideSkillDescription();
  teamsRoot.replaceChildren();
  state.teams.forEach((team, teamIndex) => {
    const teamNode = teamTemplate.content.firstElementChild.cloneNode(true);
    const nameInput = teamNode.querySelector(".team-name");
    const formationSelect = teamNode.querySelector(".formation-select");
    const meta = teamNode.querySelector(".team-meta");
    const slots = teamNode.querySelector(".slots");

    applyFormationToTeam(team);
    nameInput.value = team.name;
    fillFormationOptions(formationSelect);
    formationSelect.value = team.formationId;
    nameInput.addEventListener("input", () => {
      team.name = nameInput.value.trim() || `队伍 ${teamIndex + 1}`;
      updateOutput();
    });
    formationSelect.addEventListener("change", () => {
      team.formationId = formationSelect.value;
      applyFormationToTeam(team);
      render();
    });

    meta.textContent = formationSummary(formationById(team.formationId));
    team.slots.forEach((slot, slotIndex) => {
      slots.appendChild(renderSlot(teamIndex, slotIndex, slot));
    });
    teamsRoot.appendChild(teamNode);
  });
  updateOutput();
}

function renderSlot(teamIndex, slotIndex, slot) {
  const node = slotTemplate.content.firstElementChild.cloneNode(true);
  const title = node.querySelector(".slot-index");
  const positionSelect = node.querySelector(".position-select");
  const generalSearchInput = node.querySelector(".general-search");
  const generalSelect = node.querySelector(".general-select");
  const innateInput = node.querySelector(".innate-skill");
  const extraSelects = [...node.querySelectorAll(".extra-skill")];
  const skillDetailButtons = [...node.querySelectorAll("[data-skill-detail]")];
  const skillSearchInputs = [...node.querySelectorAll(".skill-search")];
  const allocationInputs = [...node.querySelectorAll(".alloc-input")];
  const allocationReset = node.querySelector(".allocation-reset");

  title.textContent = `${teamIndex === 0 ? "我方" : "敌方"} ${slotIndex + 1}`;
  fillGeneralOptions(generalSelect, slot.generalName, slot.generalQuery);
  generalSearchInput.value = slot.generalQuery;
  generalSelect.value = slot.generalName;
  positionSelect.value = slot.position;
  positionSelect.disabled = true;
  fillSkillOptions(extraSelects[0], slot.extraSkills[0], slot.skillQueries[0]);
  fillSkillOptions(extraSelects[1], slot.extraSkills[1], slot.skillQueries[1]);
  skillSearchInputs[0].value = slot.skillQueries[0];
  skillSearchInputs[1].value = slot.skillQueries[1];
  extraSelects[0].value = slot.extraSkills[0];
  extraSelects[1].value = slot.extraSkills[1];

  generalSelect.addEventListener("change", () => {
    hideSkillDescription();
    slot.generalName = generalSelect.value;
    slot.generalQuery = "";
    slot.allocation = { force: 0, intellect: 0, command: 0, initiative: 0 };
    slot.skillQueries = ["", ""];
    slot.extraSkills = slot.extraSkills.map((skill) => (skill === getInnateSkill(slot.generalName) ? "" : skill));
    generalSearchInput.value = "";
    fillGeneralOptions(generalSelect, slot.generalName, slot.generalQuery);
    updateSkillInputs(skillSearchInputs, slot);
    fillSkillOptions(extraSelects[0], slot.extraSkills[0], slot.skillQueries[0]);
    fillSkillOptions(extraSelects[1], slot.extraSkills[1], slot.skillQueries[1]);
    updateAllocationInputs(allocationInputs, slot);
    updateSlotCard(node, slot);
    updateOutput();
  });
  generalSearchInput.addEventListener("input", () => {
    slot.generalQuery = generalSearchInput.value;
    fillGeneralOptions(generalSelect, slot.generalName, slot.generalQuery);
    updateGeneralMatchLabel(node, slot);
  });
  positionSelect.addEventListener("change", () => {
    slot.position = positionSelect.value;
    updateOutput();
  });
  extraSelects.forEach((select, index) => {
    select.addEventListener("change", () => {
      hideSkillDescription();
      const selected = select.value;
      const otherIndex = index === 0 ? 1 : 0;
      if (selected && selected === slot.extraSkills[otherIndex]) {
        slot.extraSkills[otherIndex] = "";
        extraSelects[otherIndex].value = "";
      }
      if (selected && selected === getInnateSkill(slot.generalName)) {
        select.value = "";
      }
      slot.extraSkills[index] = select.value;
      updateSlotCard(node, slot);
      updateOutput();
    });
  });
  innateInput.addEventListener("click", () => {
    if (innateInput.dataset.skillName) showSkillDescription(innateInput.dataset.skillName, innateInput);
  });
  skillDetailButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.skillName) showSkillDescription(button.dataset.skillName, button);
    });
  });
  skillSearchInputs.forEach((input, index) => {
    input.addEventListener("input", () => {
      slot.skillQueries[index] = input.value;
      fillSkillOptions(extraSelects[index], slot.extraSkills[index], slot.skillQueries[index]);
      updateSkillMatchLabel(node, slot);
    });
  });
  allocationInputs.forEach((input) => {
    input.addEventListener("input", () => {
      updateAllocationFromInput(slot, input);
      updateAllocationInputs(allocationInputs, slot);
      updateSlotCard(node, slot);
      updateOutput();
    });
  });
  allocationReset.addEventListener("click", () => {
    slot.allocation = { force: 0, intellect: 0, command: 0, initiative: 0 };
    updateAllocationInputs(allocationInputs, slot);
    updateSlotCard(node, slot);
    updateOutput();
  });

  updateAllocationInputs(allocationInputs, slot);
  updateSlotCard(node, slot);
  updateGeneralMatchLabel(node, slot);
  updateSkillMatchLabel(node, slot);
  return node;
}

function fillGeneralOptions(select, currentValue = "", query = "") {
  select.replaceChildren();
  const filtered = filteredGenerals(query);
  const visibleNames = new Set(filtered.map((general) => general.name));

  if (currentValue && !visibleNames.has(currentValue)) {
    const currentGroup = document.createElement("optgroup");
    currentGroup.label = "当前已选";
    currentGroup.appendChild(generalOption(findGeneral(currentValue) ?? { name: currentValue }));
    select.appendChild(currentGroup);
  }

  for (const general of filtered) {
    select.appendChild(generalOption(general));
  }
  select.value = currentValue;
}

function generalOption(general) {
  const tags = [general.faction, general.troop_type, ...(general.roles ?? [])].filter(Boolean);
  return new Option(`${general.name}${tags.length ? ` · ${tags.join("/")}` : ""}`, general.name);
}

function filteredGenerals(queryText = "") {
  const query = queryText.trim().toLocaleLowerCase("zh-CN");
  return state.generals.filter((general) => !query || generalSearchText(general).includes(query));
}

function generalSearchText(general) {
  return [general.name, general.faction, general.troop_type, ...(general.roles ?? [])]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase("zh-CN");
}

function fillFormationOptions(select) {
  select.replaceChildren();
  for (const formation of FORMATIONS) {
    select.appendChild(new Option(formation.name, formation.id));
  }
}

function fillSkillOptions(select, currentValue = "", query = "") {
  select.replaceChildren(new Option("不携带", ""));
  const filtered = filteredSkills(query);
  const visibleNames = new Set(filtered.map((skill) => skill.name));

  if (currentValue && !visibleNames.has(currentValue)) {
    const currentGroup = document.createElement("optgroup");
    currentGroup.label = "当前已选";
    const currentSkill = findSkill(currentValue);
    currentGroup.appendChild(skillOption(currentSkill ?? { name: currentValue, type: "", owner: "" }));
    select.appendChild(currentGroup);
  }

  for (const type of SKILL_TYPE_ORDER) {
    const groupSkills = filtered.filter((skill) => normalizeSkillType(skill.type) === type);
    if (!groupSkills.length) {
      continue;
    }
    const group = document.createElement("optgroup");
    group.label = `${type}（${groupSkills.length}）`;
    for (const skill of groupSkills) {
      group.appendChild(skillOption(skill));
    }
    select.appendChild(group);
  }
  select.value = currentValue;
}

function skillOption(skill) {
  const type = skill.type ? ` · ${skill.type}` : "";
  const owner = skill.owner && skill.owner !== "通用战法" ? ` · ${skill.owner}` : "";
  const traits = Array.isArray(skill.traits) && skill.traits.length ? ` · ${skill.traits.join("/")}` : "";
  return new Option(`${skill.name}${type}${owner}${traits}`, skill.name);
}

function filteredSkills(queryText = "") {
  const query = queryText.trim().toLocaleLowerCase("zh-CN");
  return state.skills
    .filter((skill) => {
      if (!query) {
        return true;
      }
      return skillSearchText(skill).includes(query);
    })
    .sort((left, right) => {
      const typeDiff = SKILL_TYPE_ORDER.indexOf(normalizeSkillType(left.type)) - SKILL_TYPE_ORDER.indexOf(normalizeSkillType(right.type));
      if (typeDiff !== 0) {
        return typeDiff;
      }
      return left.name.localeCompare(right.name, "zh-CN");
    });
}

function skillSearchText(skill) {
  return [skill.name]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase("zh-CN");
}

function normalizeSkillType(type) {
  return SKILL_TYPE_ORDER.includes(type) ? type : "主动";
}

function updateSlotCard(node, slot) {
  const general = findGeneral(slot.generalName);
  const innate = getInnateSkill(slot.generalName);
  node.querySelector(".general-name").textContent = general?.name ?? "-";
  node.querySelector(".general-tags").textContent = general
    ? [general.faction, general.troop_type, ...(general.roles ?? [])].filter(Boolean).join(" · ")
    : "";
  const innateButton = node.querySelector(".innate-skill");
  innateButton.textContent = innate || "未配置";
  innateButton.dataset.skillName = innate || "";
  innateButton.disabled = !innate;
  [...node.querySelectorAll("[data-skill-detail]")].forEach((button, index) => {
    const skillName = slot.extraSkills[index] || "";
    button.dataset.skillName = skillName;
    button.textContent = skillName ? `查看「${skillName}」描述` : "查看描述";
    button.disabled = !skillName;
  });
  for (const key of STAT_KEYS) {
    node.querySelector(`[data-stat="${key}"]`).textContent = general ? estimateStat(general, key, slot) : "0";
  }
  updateAllocationLeft(node, slot);
}

function showSkillDescription(skillName, anchor) {
  const skill = findSkill(skillName);
  if (!skill) return;
  if (!skillDescriptionDialog.hidden && activeSkillDescriptionAnchor === anchor) {
    hideSkillDescription();
    return;
  }
  hideSkillDescription();
  skillDescriptionTitle.textContent = skill.name;
  skillDescriptionMeta.textContent = [skill.type, skill.owner || "通用战法"].filter(Boolean).join(" · ");
  skillDescriptionText.textContent = skill.raw_text
    ? skill.raw_text.replace(/\d+(?:\.\d+)?%?→(\d+(?:\.\d+)?%?)/g, "$1")
    : "暂无原始文本描述";
  activeSkillDescriptionAnchor = anchor;
  anchor.setAttribute("aria-expanded", "true");
  skillDescriptionDialog.hidden = false;
  positionSkillDescription();
}

function hideSkillDescription() {
  skillDescriptionDialog.hidden = true;
  activeSkillDescriptionAnchor?.setAttribute("aria-expanded", "false");
  activeSkillDescriptionAnchor = null;
}

function positionSkillDescription() {
  const anchor = activeSkillDescriptionAnchor;
  if (!anchor || skillDescriptionDialog.hidden) return;
  if (!anchor.isConnected) {
    hideSkillDescription();
    return;
  }
  const rect = anchor.getBoundingClientRect();
  if (rect.bottom <= 0 || rect.top >= window.innerHeight || rect.right <= 0 || rect.left >= window.innerWidth) {
    hideSkillDescription();
    return;
  }
  const width = skillDescriptionDialog.offsetWidth;
  const height = skillDescriptionDialog.offsetHeight;
  const margin = 12;
  const gap = 8;
  let left;
  let top = rect.top;
  if (window.innerWidth - rect.right >= width + margin + gap) {
    left = rect.right + gap;
  } else if (rect.left >= width + margin + gap) {
    left = rect.left - width - gap;
  } else {
    left = clamp(rect.left, margin, window.innerWidth - width - margin);
    top = window.innerHeight - rect.bottom >= height + margin + gap
      ? rect.bottom + gap
      : rect.top - height - gap;
  }
  skillDescriptionDialog.style.left = `${clamp(left, margin, window.innerWidth - width - margin)}px`;
  skillDescriptionDialog.style.top = `${clamp(top, margin, window.innerHeight - height - margin)}px`;
}

function updateSkillInputs(inputs, slot) {
  inputs.forEach((input, index) => {
    input.value = slot.skillQueries[index] ?? "";
  });
}

function updateGeneralMatchLabel(node, slot) {
  const label = node.querySelector(".general-label");
  const query = slot.generalQuery ?? "";
  label.textContent = query ? `武将 · 匹配 ${filteredGenerals(query).length}` : "武将";
}

function updateSkillMatchLabel(node, slot) {
  const labels = [...node.querySelectorAll(".skills .field > span")].slice(1);
  labels.forEach((label, index) => {
    const query = slot.skillQueries[index] ?? "";
    const count = filteredSkills(query).length;
    label.textContent = query ? `携带 ${index + 1} · 匹配 ${count}` : `携带 ${index + 1}`;
  });
}

function updateOutput() {
  jsonOutput.textContent = JSON.stringify(buildBattleConfig(), null, 2);
}

async function simulateBattle() {
  simulateButton.disabled = true;
  simulateButton.textContent = "对战中...";
  setStatus("正在模拟对战", false);
  try {
    const response = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        battle: buildBattleConfig(),
        seed: seedInput.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error ?? "模拟失败");
    }
    renderBattleResult(payload);
    setStatus("对战完成", false);
  } catch (error) {
    battleResult.hidden = false;
    battleSummary.innerHTML = `<strong>无法开始对战</strong><span>${escapeHtml(String(error.message ?? error))}</span>`;
    battleStats.innerHTML = "";
    battleRoundNav.replaceChildren();
    currentLogSections = [];
    currentLogEntries = [];
    battleLog.textContent = "请用 python web/server.py 启动本地服务，然后打开 http://localhost:8000/web/index.html";
    setStatus("模拟接口不可用", true);
  } finally {
    simulateButton.disabled = false;
    simulateButton.textContent = "开始对战";
  }
}

function renderBattleResult(result) {
  battleResult.hidden = false;
  const [leftTeam, rightTeam] = result.teams;
  battleSummary.innerHTML = `
    <div class="report-scoreboard">
      ${renderTeamScore(leftTeam, "left")}
      <div class="battle-outcome">
        <span>战果</span>
        <strong>${escapeHtml(result.winner_name === "平局" ? "平" : result.winner_name === leftTeam.name ? "胜" : "败")}</strong>
        <small>${escapeHtml(result.winner_name)} · ${formatNumber(result.rounds)} 回合</small>
      </div>
      ${renderTeamScore(rightTeam, "right")}
    </div>
  `;
  battleStats.innerHTML = renderSourceStats(result);
  renderBattleLog(result);
  battleResult.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderBattleLog(result) {
  const fallback = (result.log || []).map((text) => ({ text, states: {} }));
  currentLogEntries = Array.isArray(result.log_entries) && result.log_entries.length ? result.log_entries : fallback;
  const leftTeamName = result.teams?.[0]?.name ?? "";
  currentLogSections = partitionBattleLog(currentLogEntries);
  battleRoundNav.innerHTML = currentLogSections
    .map((section, index) => `<button class="battle-round-button${index === 0 ? " active" : ""}" type="button" data-round-key="${section.key}" aria-label="跳转到${section.title}${section.key === "setup" ? "" : "行动顺序"}" ${index === 0 ? 'aria-current="true"' : ""}>${section.label}</button>`)
    .join("");
  battleLog.innerHTML = currentLogSections
    .map((section) => `<section class="battle-log-round" data-round-key="${section.key}">
      <h3>${section.title}</h3>
      ${section.lines.map(({ entry, index }) => `<div class="battle-log-line${index === section.jumpIndex ? " round-action-order" : ""}" data-log-index="${index}">${renderLogLine(entry, index, leftTeamName)}</div>`).join("")}
    </section>`)
    .join("");
  battleLog.scrollTop = 0;
  battleRoundNav.scrollTop = 0;
}

function partitionBattleLog(entries) {
  const labels = ["", "一", "二", "三", "四", "五", "六", "七", "八"];
  const sections = [{ key: "setup", label: "布阵", title: "布阵", jumpIndex: null, lines: [] }];
  let current = sections[0];
  entries.forEach((entry, index) => {
    const text = String(entry.text ?? "");
    const marker = text.match(/^== 第\s*(\d+)\s*回合 ==$/);
    if (marker) {
      const round = Number(marker[1]);
      const title = `第${labels[round] || round}回合`;
      current = { key: String(round), label: labels[round] || String(round), title, jumpIndex: null, lines: [] };
      sections.push(current);
      return;
    }
    current.lines.push({ entry, index });
    if (current.key !== "setup" && text.startsWith("行动顺序：")) current.jumpIndex = index;
  });
  return sections;
}

function setActiveBattleRound(key) {
  battleRoundNav.querySelectorAll(".battle-round-button").forEach((button) => {
    const active = button.dataset.roundKey === key;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  });
}

battleRoundNav.addEventListener("click", (event) => {
  const button = event.target.closest(".battle-round-button");
  if (!button) return;
  const section = currentLogSections.find((item) => item.key === button.dataset.roundKey);
  if (!section) return;
  const target = section.jumpIndex == null
    ? battleLog.querySelector(`.battle-log-round[data-round-key="${section.key}"]`)
    : battleLog.querySelector(`.battle-log-line[data-log-index="${section.jumpIndex}"]`);
  if (!target) return;
  battleLog.scrollTop += target.getBoundingClientRect().top - battleLog.getBoundingClientRect().top;
  setActiveBattleRound(section.key);
});

battleLog.addEventListener("scroll", () => {
  const top = battleLog.getBoundingClientRect().top + 10;
  let visibleKey = currentLogSections[0]?.key;
  for (const section of battleLog.querySelectorAll(".battle-log-round")) {
    if (section.getBoundingClientRect().top > top) break;
    visibleKey = section.dataset.roundKey;
  }
  if (visibleKey) setActiveBattleRound(visibleKey);
});

function renderLogLine(entry, index, leftTeamName) {
  const text = String(entry.text ?? "");
  const states = entry.states ?? {};
  const names = Object.keys(states).sort((left, right) => right.length - left.length);
  if (!names.length) {
    return escapeHtml(text);
  }

  let cursor = 0;
  let html = "";
  while (cursor < text.length) {
    let matchName = "";
    let matchIndex = text.length;
    for (const name of names) {
      const found = text.indexOf(name, cursor);
      if (found >= 0 && found < matchIndex) {
        matchName = name;
        matchIndex = found;
      }
    }
    if (!matchName) {
      html += escapeHtml(text.slice(cursor));
      break;
    }
    html += escapeHtml(text.slice(cursor, matchIndex));
    const snapshots = states[matchName] || [];
    const side = snapshots[0]?.team === leftTeamName ? "ally" : "enemy";
    html += `<button class="log-general-name ${side}" type="button" data-log-index="${index}" data-general-name="${escapeHtml(matchName)}">${escapeHtml(matchName)}</button>`;
    cursor = matchIndex + matchName.length;
  }
  return html;
}

function renderGeneralStateTooltip(snapshots) {
  return `<button class="state-tooltip-close" type="button" aria-label="关闭状态表">×</button>` + snapshots
    .map((snapshot) => {
      const values = Object.entries(snapshot.values || {});
      const rates = Object.entries(snapshot.rates || {});
      const effects = [...(snapshot.effects || []), ...(snapshot.statuses || []).map(statusToEffect)];
      return `
        <section class="state-tooltip-general">
          <header>
            <strong>${escapeHtml(snapshot.name)}</strong>
            <span>${escapeHtml(snapshot.team || "")} · ${snapshot.position === "front" ? "前排" : "后排"}</span>
          </header>
          <dl class="state-value-list">
            ${values.map(([name, value]) => `<div><dt>${escapeHtml(name)}</dt><dd>${formatStateValue(value)}</dd></div>`).join("")}
          </dl>
          <dl class="state-rate-list">
            ${rates.map(([name, value]) => `<div><dt>${escapeHtml(name)}</dt><dd>${formatPercent(value)}</dd></div>`).join("")}
          </dl>
          <div class="state-effect-list">
            ${effects.length ? effects.map(renderStateEffect).join("") : `<span class="state-empty">当前无额外状态</span>`}
          </div>
        </section>
      `;
    })
    .join("");
}

function statusToEffect(status) {
  const rounds = status.remaining_rounds == null ? null : Number(status.remaining_rounds);
  return {
    name: status.name,
    source: status.source,
    polarity: status.polarity,
    remaining_rounds: rounds,
    details: [`${Number(status.stacks || 1)} 层`],
  };
}

function renderStateEffect(effect) {
  const duration = effect.remaining_rounds == null ? "所有回合" : `剩余 ${formatNumber(effect.remaining_rounds)} 回合`;
  const source = effect.source ? ` · ${escapeHtml(effect.source)}` : "";
  return `
    <div class="state-effect ${effect.polarity === "negative" ? "negative" : effect.polarity === "mixed" ? "mixed" : "positive"}">
      <strong>【${escapeHtml(effect.name)}】</strong>
      <span>${escapeHtml((effect.details || []).join("，"))}</span>
      <small>${duration}${source}</small>
    </div>
  `;
}

function formatStateValue(value) {
  return typeof value === "number" ? formatNumber(value) : escapeHtml(value);
}

function formatPercent(value) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

function showGeneralStateTooltip(target) {
  const entry = currentLogEntries[Number(target.dataset.logIndex)];
  const snapshots = entry?.states?.[target.dataset.generalName] || [];
  if (!snapshots.length) {
    return;
  }
  generalStateTooltip.innerHTML = renderGeneralStateTooltip(snapshots);
  generalStateTooltip.hidden = false;
  positionGeneralStateTooltip(target);
}

function positionGeneralStateTooltip(target) {
  const rect = target.getBoundingClientRect();
  const x = rect.right;
  const y = rect.bottom;
  const margin = 10;
  const width = generalStateTooltip.offsetWidth;
  const height = generalStateTooltip.offsetHeight;
  const left = clamp(x + 14, margin, window.innerWidth - width - margin);
  const top = clamp(y + 12, margin, window.innerHeight - height - margin);
  generalStateTooltip.style.left = `${left}px`;
  generalStateTooltip.style.top = `${top}px`;
}

battleLog.addEventListener("click", (event) => {
  const target = event.target.closest(".log-general-name");
  if (target) {
    event.stopPropagation();
    showGeneralStateTooltip(target);
  }
});
generalStateTooltip.addEventListener("click", (event) => {
  event.stopPropagation();
  if (event.target.closest(".state-tooltip-close")) generalStateTooltip.hidden = true;
});
skillDescriptionDialog.addEventListener("click", (event) => {
  if (event.target.closest(".skill-description-close")) hideSkillDescription();
});
document.addEventListener("click", (event) => {
  generalStateTooltip.hidden = true;
  if (!skillDescriptionDialog.contains(event.target)
    && !activeSkillDescriptionAnchor?.contains(event.target)) hideSkillDescription();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") generalStateTooltip.hidden = true;
  if (event.key === "Escape") hideSkillDescription();
});
window.addEventListener("resize", positionSkillDescription);
window.addEventListener("scroll", (event) => {
  if (!skillDescriptionDialog.contains(event.target)) hideSkillDescription();
}, true);

function renderTeamScore(team, side) {
  const maxTroops = Math.max(1, Number(team.max_troops || 0));
  const currentTroops = Number(team.total_troops || 0);
  const troopPercent = clamp((currentTroops / maxTroops) * 100, 0, 100);
  return `
    <section class="team-score ${side}">
      <div class="team-score-head">
        <strong>${escapeHtml(team.name)}</strong>
        <span>${escapeHtml(team.formation_name || "未设置阵型")}</span>
      </div>
      <div class="troop-track"><span style="width:${troopPercent}%"></span></div>
      <div class="team-score-values">
        <span>${formatNumber(currentTroops)}/${formatNumber(maxTroops)}</span>
        <b>战损 ${formatNumber(team.troop_loss)}</b>
      </div>
    </section>
  `;
}

function renderSourceStats(result) {
  const stats = Array.isArray(result.stats) ? result.stats : [];
  if (!stats.length) {
    return `<div class="stats-empty">暂无伤害或治疗统计</div>`;
  }

  return `<div class="report-armies">${result.teams
    .map(
      (team, teamIndex) => `
        <section class="report-team ${teamIndex === 0 ? "ally" : "enemy"}">
          <h3>${escapeHtml(team.name)} · ${escapeHtml(team.formation_name || "未设置阵型")}</h3>
          <div class="general-reports">
            ${team.generals.map((general) => renderGeneralReport(team, general, stats)).join("")}
          </div>
        </section>
      `
    )
    .join("")}</div>`;
}

function renderGeneralReport(team, general, stats) {
  const maxTroops = Math.max(1, Number(general.max_troops || 0));
  const currentTroops = Number(general.troops || 0);
  const troopPercent = clamp((currentTroops / maxTroops) * 100, 0, 100);
  const actorStats = stats.filter((item) => item.team === team.name && item.actor === general.name);
  const sourceOrder = [...(general.skills || []), "普通攻击"];
  actorStats.sort((left, right) => {
    const leftIndex = sourceOrder.indexOf(left.source);
    const rightIndex = sourceOrder.indexOf(right.source);
    const normalizedLeft = leftIndex < 0 ? sourceOrder.length : leftIndex;
    const normalizedRight = rightIndex < 0 ? sourceOrder.length : rightIndex;
    return normalizedLeft - normalizedRight;
  });
  const totalDamage = actorStats.reduce((total, item) => total + Number(item.damage || 0), 0);
  const totalHealing = actorStats.reduce((total, item) => total + Number(item.healing || 0), 0);

  return `
    <article class="general-report ${general.is_alive ? "" : "defeated"}">
      <header>
        <div class="general-emblem">${escapeHtml(String(general.name || "?").slice(0, 1))}</div>
        <div>
          <strong>${escapeHtml(general.name)}</strong>
          <span>${general.is_alive ? "存活" : "阵亡"}</span>
        </div>
      </header>
      <div class="general-troops">
        <div class="troop-track"><span style="width:${troopPercent}%"></span></div>
        <span>${formatNumber(currentTroops)}/${formatNumber(maxTroops)}</span>
      </div>
      <div class="general-totals">
        <span>总伤害 <b>${formatNumber(totalDamage)}</b></span>
        <span>总治疗 <b>${formatNumber(totalHealing)}</b></span>
      </div>
      <div class="skill-report-list">
        ${actorStats.map(renderSkillReportRow).join("") || `<div class="stats-empty">暂无战法记录</div>`}
      </div>
    </article>
  `;
}

function renderSkillReportRow(item) {
  return `
    <div class="skill-report-row">
      <div class="skill-report-name">
        <strong>${escapeHtml(item.source)}</strong>
        <span>×${formatNumber(item.activations)}</span>
      </div>
      <div class="skill-report-values">
        <span class="damage-value">伤 ${formatNumber(item.damage)}</span>
        <span class="healing-value">治 ${formatNumber(item.healing)}</span>
      </div>
    </div>
  `;
}

function buildBattleConfig() {
  return {
    team_a: buildTeam(state.teams[0]),
    team_b: buildTeam(state.teams[1]),
    max_rounds: 8,
  };
}

function buildTeam(team) {
  const formation = formationById(team.formationId);
  return {
    name: team.name,
    formation: {
      id: formation.id,
      name: formation.name,
      positions: [...formation.positions],
      target_weights: [...formation.targetWeights],
      effects: formation.effects.map((effect) => ({ ...effect })),
    },
    generals: team.slots.map((slot, slotIndex) => buildGeneral(slot, team, slotIndex)),
  };
}

function buildGeneral(slot, team, slotIndex) {
  const general = findGeneral(slot.generalName);
  const innate = general?.innate_skill ?? "";
  const skills = [innate, ...slot.extraSkills].filter(Boolean);
  const formation = formationById(team.formationId);
  const position = formation.positions[slotIndex];
  return {
    name: general?.name ?? slot.generalName,
    troops: readTroops(),
    max_troops: readTroops(),
    force: estimateStat(general, "force", slot),
    intellect: estimateStat(general, "intellect", slot),
    command: estimateStat(general, "command", slot),
    initiative: estimateStat(general, "initiative", slot),
    faction: general?.faction ?? "",
    troop_type: general?.troop_type ?? "",
    race: general?.race ?? "",
    position,
    basic_target_weight: formation.targetWeights[slotIndex],
    modifiers: formationModifiersFor(formation, position),
    allocated_free_points: { ...slot.allocation },
    skills,
  };
}

function estimateStat(general, stat, slot = null) {
  if (!general) {
    return 1;
  }
  const entry = general.stats?.[stat];
  const level = readLevel();
  const currentLevel = Number(general.current_level ?? 5);
  const value = Number(entry?.current ?? 1) + Number(entry?.growth ?? 0) * (level - currentLevel);
  const allocated = Number(slot?.allocation?.[stat] ?? 0);
  return Math.max(1, Math.floor(value + allocated));
}

function updateAllocationFromInput(slot, input) {
  const stat = input.dataset.alloc;
  const previous = Number(slot.allocation[stat] ?? 0);
  const requested = clamp(Math.floor(Number(input.value || 0)), 0, FREE_ATTRIBUTE_POINTS);
  slot.allocation[stat] = 0;
  const room = Math.max(0, FREE_ATTRIBUTE_POINTS - allocationTotal(slot));
  slot.allocation[stat] = Math.min(requested, previous + room);
}

function updateAllocationInputs(inputs, slot) {
  for (const input of inputs) {
    const stat = input.dataset.alloc;
    input.value = String(slot.allocation[stat] ?? 0);
  }
}

function updateAllocationLeft(node, slot) {
  const left = FREE_ATTRIBUTE_POINTS - allocationTotal(slot);
  const label = node.querySelector(".allocation-left");
  label.textContent = `剩余 ${left}`;
  label.classList.toggle("over", left < 0);
}

function allocationTotal(slot) {
  return STAT_KEYS.reduce((total, key) => total + Number(slot.allocation?.[key] ?? 0), 0);
}

function readLevel() {
  return clamp(Number(levelInput.value || 50), 5, 50);
}

function readTroops() {
  return Math.max(1, Math.floor(Number(troopsInput.value || 10000)));
}

function applyFormationToTeam(team) {
  const formation = formationById(team.formationId);
  team.slots.forEach((slot, index) => {
    slot.position = formation.positions[index];
  });
}

function formationById(id) {
  return FORMATIONS.find((formation) => formation.id === id) ?? FORMATIONS[0];
}

function formationSummary(formation) {
  const weights = formation.targetWeights.map((weight) => `${Math.round(weight * 100)}%`).join(" / ");
  return `${formation.name} · 受击率 ${weights} · ${formation.effects.map((effect) => effect.text).join("，")}`;
}

function formationModifiersFor(formation, position) {
  return formation.effects
    .filter((effect) => effect.lane === position)
    .map((effect) => ({
      name: formation.name,
      stat: effect.stat,
      value: effect.value,
    }));
}

function findGeneral(name) {
  return state.generals.find((general) => general.name === name);
}

function findSkill(name) {
  return state.skills.find((skill) => skill.name === name);
}

function getInnateSkill(generalName) {
  return findGeneral(generalName)?.innate_skill ?? "";
}

function setStatus(message, isError) {
  dataStatus.textContent = message;
  dataStatus.className = isError ? "error" : "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

copyButton.addEventListener("click", async () => {
  await navigator.clipboard.writeText(jsonOutput.textContent);
  setStatus("已复制 JSON", false);
  dataStatus.className = "toast";
});

downloadButton.addEventListener("click", () => {
  const blob = new Blob([jsonOutput.textContent], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "battle.json";
  link.click();
  URL.revokeObjectURL(url);
});

resetButton.addEventListener("click", () => {
  resetTeams();
  render();
  battleResult.hidden = true;
  setStatus(`${state.generals.length} 名武将，${state.skills.length} 个战法`, false);
});

toggleConfigButton.addEventListener("click", () => {
  configPreview.hidden = !configPreview.hidden;
  workspace.classList.toggle("show-config", !configPreview.hidden);
  toggleConfigButton.textContent = configPreview.hidden ? "显示配置" : "隐藏配置";
  toggleConfigButton.setAttribute("aria-expanded", String(!configPreview.hidden));
});

levelInput.addEventListener("input", render);
troopsInput.addEventListener("input", updateOutput);
simulateButton.addEventListener("click", simulateBattle);
