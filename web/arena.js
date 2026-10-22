const STORAGE_KEY = "sanmou-arena-agent-v2";
const ADVISOR_SETTINGS_KEY = "sanmou-arena-advisor-settings-v1";
const ADVISOR_API_KEY_KEY = "sanmou-arena-advisor-key-v1";
const INITIAL_GENERAL_COUNT = 4;
const INITIAL_SKILL_COUNT = 8;
const ROUND_KINDS = ["general", "skill", "skill", "general", "skill", "skill"];
const state = {
  generalsData: [],
  skillsData: [],
  initialGenerals: [],
  initialSkills: [],
  ownedGenerals: [],
  ownedSkills: [],
  rounds: ROUND_KINDS.map((kind) => ({ kind, groups: [[], [], []], selected: null, accepted: false, skipped: false, directEntry: false, recordedGroup: ["", "", ""] })),
  draftIndex: 0,
  draftedGenerals: [],
  draftedSkills: [],
  generals: [],
  skills: [],
  support: { baseGeneral: "", baseSkills: ["", ""], kit: "none", transformed: "", transformCategory: "physical", transformResult: "", orangeSkills: ["", ""], orangeCategory: "weapon", orangeResults: ["", ""], purpleSkill: "", dirty: true },
  plan: null,
  advisorMessages: [],
};
let advisorSettings = { endpoint: "", model: "" };
let advisorSending = false;

const byId = (id) => document.getElementById(id);
const generalByName = (name) => state.generalsData.find((item) => item.name === name);
const skillByName = (name) => state.skillsData.find((item) => item.name === name);

async function initialize() {
  try {
    const [generalData, skillData] = await Promise.all([
      fetch("../data/generals.json").then((response) => response.json()),
      fetch("../data/skills.json").then((response) => response.json()),
    ]);
    state.generalsData = generalData.generals || [];
    state.skillsData = skillData.skills || [];
    hydrate();
    loadAdvisorSettings();
    fillCatalogs();
    bindEvents();
    renderAll();
  } catch (error) {
    document.body.innerHTML = `<main class="arena-shell"><h1>演武资料读取失败</h1><p>${escapeHtml(error.message)}</p><a href="./index.html">返回模拟器</a></main>`;
  }
}

function hydrate() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (!saved) return;
    for (const key of ["initialGenerals", "initialSkills", "ownedGenerals", "ownedSkills", "draftedGenerals", "draftedSkills", "generals", "skills"]) {
      if (Array.isArray(saved[key])) state[key] = saved[key];
    }
    if (Array.isArray(saved.rounds) && saved.rounds.length === ROUND_KINDS.length) {
      state.rounds = saved.rounds.map((round) => ({
        ...round,
        accepted: Boolean(round.accepted ?? round.selected !== null),
        skipped: Boolean(round.skipped),
        directEntry: Boolean(round.directEntry),
        recordedGroup: Array.isArray(round.recordedGroup) ? round.recordedGroup : ["", "", ""],
      }));
    }
    if (Array.isArray(saved.advisorMessages)) state.advisorMessages = saved.advisorMessages.filter((message) => ["user", "assistant"].includes(message.role) && typeof message.content === "string").slice(-40);
    if (Number.isInteger(saved.draftIndex)) state.draftIndex = Math.min(5, Math.max(0, saved.draftIndex));
    if (saved.support) state.support = { ...state.support, ...saved.support };
    if (["initial", "draft", "support", "teams"].includes(saved.stage)) state.stage = saved.stage;
    if (saved.plan) state.plan = saved.plan;
  } catch {
    localStorage.removeItem(STORAGE_KEY);
  }
}

function persist() {
  const active = document.querySelector(".stage-tab.is-active")?.dataset.stage || "initial";
  const payload = { ...state, stage: active, generalsData: undefined, skillsData: undefined };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    byId("saveState").textContent = "已保存在本地浏览器";
  } catch {
    byId("saveState").textContent = "本地保存失败";
  }
}

function loadAdvisorSettings() {
  try { advisorSettings = { ...advisorSettings, ...JSON.parse(localStorage.getItem(ADVISOR_SETTINGS_KEY) || "{}") }; } catch { /* Keep empty settings. */ }
}

function openAdvisor() {
  byId("advisorDrawer").hidden = false;
  renderAdvisorMessages();
  updateAdvisorSummary();
  if (!advisorSettings.endpoint || !advisorSettings.model) openAdvisorSettings();
  else byId("advisorInput").focus();
}

function closeAdvisor() { byId("advisorDrawer").hidden = true; }

function openAdvisorSettings() {
  byId("advisorEndpoint").value = advisorSettings.endpoint;
  byId("advisorModel").value = advisorSettings.model;
  byId("advisorApiKey").value = sessionStorage.getItem(ADVISOR_API_KEY_KEY) || "";
  byId("advisorSettingsDialog").showModal();
}

function saveAdvisorSettings(event) {
  event.preventDefault();
  const endpoint = byId("advisorEndpoint").value.trim();
  const model = byId("advisorModel").value.trim();
  try {
    const parsed = new URL(endpoint);
    if (!(["https:", "http:"].includes(parsed.protocol)) || parsed.username || parsed.password) throw new Error("invalid");
  } catch {
    return toast("请输入有效的 HTTP 或 HTTPS 兼容接口地址。");
  }
  advisorSettings = { endpoint, model };
  localStorage.setItem(ADVISOR_SETTINGS_KEY, JSON.stringify(advisorSettings));
  const key = byId("advisorApiKey").value.trim();
  if (key) sessionStorage.setItem(ADVISOR_API_KEY_KEY, key);
  else sessionStorage.removeItem(ADVISOR_API_KEY_KEY);
  byId("advisorSettingsDialog").close();
  updateAdvisorSummary();
  byId("advisorInput").focus();
}

function clearAdvisorKey() {
  sessionStorage.removeItem(ADVISOR_API_KEY_KEY);
  byId("advisorApiKey").value = "";
  updateAdvisorSummary();
}

function getAdvisorPool() {
  let generalNames;
  let skillNames;
  if (!state.stage || state.stage === "initial") {
    generalNames = state.initialGenerals;
    skillNames = state.initialSkills;
  } else if (state.stage === "draft") {
    const hasDraft = state.rounds.some((round) => round.accepted);
    generalNames = hasDraft ? state.draftedGenerals : state.initialGenerals;
    skillNames = hasDraft ? state.draftedSkills : state.initialSkills;
  } else {
    prepareCurrentTeamPool();
    generalNames = state.generals;
    skillNames = state.skills;
  }
  return {
    generalNames: [...new Set(generalNames.filter((name) => generalByName(name)))],
    skillNames: [...new Set(skillNames.filter((name) => skillByName(name)))],
  };
}

function updateAdvisorSummary() {
  if (!byId("advisorPoolSummary")) return;
  const pool = getAdvisorPool();
  const nextRound = nextDraftIndex();
  byId("advisorPoolSummary").textContent = `${pool.generalNames.length} 名武将 · ${pool.skillNames.length} 个战法${nextRound >= 0 ? ` · 第 ${nextRound + 1} 轮待处理` : ""}`;
  const configured = Boolean(advisorSettings.endpoint && advisorSettings.model);
  byId("advisorConnectionState").textContent = configured ? `模型：${advisorSettings.model}${sessionStorage.getItem(ADVISOR_API_KEY_KEY) ? " · 密钥已就绪" : ""}` : "先配置模型接口";
  byId("advisorSend").disabled = advisorSending || !configured;
}

function renderAdvisorMessages() {
  const root = byId("advisorMessages");
  if (!root) return;
  root.replaceChildren();
  if (!state.advisorMessages.length) {
    const welcome = document.createElement("div");
    welcome.className = "advisor-message assistant";
    const author = document.createElement("strong");
    author.textContent = "构筑顾问";
    const content = document.createElement("p");
    content.textContent = "我会结合当前卡池、战法描述、目标与触发机制以及成熟队伍思路分析。会明确区分项目记录、已确认经验和模型判断，不只按定位凑齐三人。";
    welcome.append(author, content);
    root.append(welcome);
  } else {
    state.advisorMessages.forEach((message) => {
      const bubble = document.createElement("div");
      bubble.className = `advisor-message ${message.role}`;
      const author = document.createElement("strong");
      author.textContent = message.role === "user" ? "你" : "构筑顾问";
      const content = document.createElement("p");
      content.textContent = message.content;
      bubble.append(author, content);
      root.append(bubble);
    });
  }
  if (advisorSending) {
    const pending = document.createElement("div");
    pending.className = "advisor-message assistant is-pending";
    pending.textContent = "正在结合当前卡池分析……";
    root.append(pending);
  }
  root.scrollTop = root.scrollHeight;
  updateAdvisorSummary();
}

function advisorContext() {
  const { generalNames, skillNames } = getAdvisorPool();
  const generals = generalNames.map((name) => {
    const general = generalByName(name);
    const statsAt50 = Object.fromEntries(Object.entries(general.stats || {}).map(([key, value]) => [key, Number(((value.current || 0) + (value.growth || 0) * (50 - (general.current_level || 5))).toFixed(2))]));
    const innate = skillByName(general.innate_skill);
    return { name, faction: general.faction, troopType: general.troop_type, roles: general.roles, statsAt50, innateSkill: innate ? { name: innate.name, rawText: innate.raw_text, effects: innate.effects } : general.innate_skill };
  });
  const skills = skillNames.map((name) => {
    const skill = skillByName(name);
    return { name, owner: skill.owner, type: skill.type, activationRate: skill.activation_rate, traits: skill.traits, rawText: skill.raw_text, effects: skill.effects };
  });
  const currentRound = state.rounds[state.draftIndex];
  const plan = calculatePlan(generalNames, skillNames);
  return {
    stage: state.stage || "initial",
    poolCompleteness: { initialGenerals: state.initialGenerals.length, initialSkills: state.initialSkills.length, draftRoundsCompleted: state.rounds.filter(isRoundComplete).length },
    generals,
    skills,
    draftHistory: state.rounds.map((round, index) => ({ round: index + 1, kind: roundKindLabel(round.kind), status: round.skipped ? "skipped" : round.accepted ? "accepted" : "pending", directEntry: round.directEntry, selected: round.directEntry ? round.recordedGroup : round.accepted ? round.groups[round.selected] : undefined })),
    currentDraftOptions: currentRound && !isRoundComplete(currentRound) ? { round: state.draftIndex + 1, kind: roundKindLabel(currentRound.kind), mode: currentRound.directEntry ? "direct-entry" : "candidate-groups", candidateGroups: currentRound.directEntry ? undefined : currentRound.groups, directSelection: currentRound.directEntry ? currentRound.recordedGroup : undefined, selectedGroupIndex: currentRound.selected } : null,
    currentHeuristicPlan: plan ? plan.teams.map((team) => ({ formation: team.formation, members: team.members })) : [],
    dataLimitations: ["未录入的初始牌和战法不在当前卡池中", "红度、账号个体自由加点及韬略未完整记录", "启发式评分不是胜率或强度实测"],
  };
}

async function sendAdvisorMessage(messageText = byId("advisorInput").value) {
  const content = String(messageText || "").trim();
  if (!content || advisorSending) return;
  if (!advisorSettings.endpoint || !advisorSettings.model) {
    byId("advisorInput").value = content;
    openAdvisorSettings();
    return;
  }
  state.advisorMessages.push({ role: "user", content });
  state.advisorMessages = state.advisorMessages.slice(-40);
  byId("advisorInput").value = "";
  advisorSending = true;
  renderAdvisorMessages();
  persist();
  try {
    const request = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: advisorSettings.endpoint, model: advisorSettings.model, api_key: sessionStorage.getItem(ADVISOR_API_KEY_KEY) || "", messages: state.advisorMessages.slice(-20), context: advisorContext() }),
    };
    let response = await fetch("/api/arena/advisor", request);
    if (response.status === 404 && location.port === "8000" && ["127.0.0.1", "localhost"].includes(location.hostname)) {
      response = await fetch(`${location.protocol}//${location.hostname}:8001/api/arena/advisor`, request);
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `接口请求失败（${response.status}）`);
    state.advisorMessages.push({ role: "assistant", content: result.reply || "模型没有返回文字，请检查接口配置。" });
  } catch (error) {
    state.advisorMessages.push({ role: "assistant", content: `暂时无法连接模型：${error.message}\n请检查本地服务是否已重启、接口地址和模型 ID 是否正确。` });
  } finally {
    state.advisorMessages = state.advisorMessages.slice(-40);
    advisorSending = false;
    renderAdvisorMessages();
    persist();
  }
}

function bindEvents() {
  document.querySelectorAll(".stage-tab").forEach((button) => button.addEventListener("click", () => showStage(button.dataset.stage)));
  byId("addInitialGeneral").addEventListener("click", () => addFromInput("initialGeneralInput", "initialGenerals", 4, "武将"));
  byId("addInitialSkill").addEventListener("click", () => addFromInput("initialSkillInput", "initialSkills", INITIAL_SKILL_COUNT, "战法"));
  byId("initialGeneralInput").addEventListener("keydown", enterToAdd("addInitialGeneral"));
  byId("initialSkillInput").addEventListener("keydown", enterToAdd("addInitialSkill"));
  byId("startDraft").addEventListener("click", beginDraft);
  byId("backToInitial").addEventListener("click", () => showStage("initial"));
  byId("acceptDraft").addEventListener("click", acceptDraftGroup);
  byId("toggleDirectEntry").addEventListener("click", toggleDirectEntry);
  byId("skipDraft").addEventListener("click", skipDraftRound);
  byId("backToDraft").addEventListener("click", () => showStage("draft"));
  byId("addOwnedGeneral").addEventListener("click", () => addFromInput("ownedGeneralInput", "ownedGenerals", 999, "武将"));
  byId("addOwnedSkill").addEventListener("click", () => addFromInput("ownedSkillInput", "ownedSkills", 999, "战法"));
  byId("ownedGeneralInput").addEventListener("keydown", enterToAdd("addOwnedGeneral"));
  byId("ownedSkillInput").addEventListener("keydown", enterToAdd("addOwnedSkill"));
  byId("kitType").addEventListener("change", () => { state.support.kit = byId("kitType").value; state.support.dirty = true; renderKitDetails(); renderCounts(); persist(); });
  byId("finishSupport").addEventListener("click", finishSupport);
  byId("backToSupport").addEventListener("click", returnToCurrentFlow);
  byId("rebuildTeams").addEventListener("click", () => { state.plan = calculatePlan(state.generals, state.skills); renderTeams(); persist(); });
  byId("copyRoster").addEventListener("click", copyRoster);
  byId("resetArena").addEventListener("click", resetArena);
  byId("openAdvisor").addEventListener("click", openAdvisor);
  byId("advisorClose").addEventListener("click", closeAdvisor);
  byId("advisorSettingsOpen").addEventListener("click", openAdvisorSettings);
  byId("advisorSettingsCancel").addEventListener("click", () => byId("advisorSettingsDialog").close());
  byId("advisorSettingsForm").addEventListener("submit", saveAdvisorSettings);
  byId("advisorClearKey").addEventListener("click", clearAdvisorKey);
  byId("advisorChatForm").addEventListener("submit", (event) => { event.preventDefault(); sendAdvisorMessage(); });
  byId("advisorInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); byId("advisorChatForm").requestSubmit(); }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !byId("advisorSettingsDialog").open) closeAdvisor();
  });
  document.querySelectorAll("[data-advisor-prompt]").forEach((button) => button.addEventListener("click", () => {
    byId("advisorInput").value = button.dataset.advisorPrompt;
    sendAdvisorMessage();
  }));
}

function enterToAdd(buttonId) {
  return (event) => { if (event.key === "Enter") { event.preventDefault(); byId(buttonId).click(); } };
}

function fillCatalogs() {
  const generalList = byId("generalCatalog");
  const skillList = byId("skillCatalog");
  state.generalsData.forEach((general) => generalList.append(new Option(`${general.name} · ${general.faction || ""} · ${general.troop_type || ""}`, general.name)));
  state.skillsData.forEach((skill) => skillList.append(new Option(`${skill.name} · ${skill.type || ""} · ${skill.traits?.join("/ ") || ""}`, skill.name)));
}

function addFromInput(inputId, key, max, label) {
  const input = byId(inputId);
  const name = input.value.trim();
  const valid = key.toLowerCase().includes("general") ? generalByName(name) : skillByName(name);
  if (!valid) return toast(`请从资料库选择有效的${label}名称。`);
  if (state[key].includes(name)) return toast(`${label}已在列表中。`);
  if (state[key].length >= max) return toast(`${label}数量已达到本阶段上限。`);
  state[key].push(name);
  input.value = "";
  renderAll();
  persist();
}

function renderAll() {
  renderTokens("initialGenerals", state.initialGenerals, (name) => removeValue("initialGenerals", name));
  renderTokens("initialSkills", state.initialSkills, (name) => removeValue("initialSkills", name));
  renderTokens("ownedGenerals", state.ownedGenerals, (name) => removeValue("ownedGenerals", name));
  renderTokens("ownedSkills", state.ownedSkills, (name) => removeValue("ownedSkills", name));
  renderCounts();
  renderDraft();
  renderSupport();
  renderTeams();
  renderAdvisorMessages();
  const activeStage = state.stage || "initial";
  showStage(activeStage, false);
}

function renderTokens(id, values, onRemove) {
  const root = byId(id);
  root.replaceChildren();
  values.forEach((name) => {
    const token = document.createElement("span");
    token.className = "token";
    const label = document.createElement("span");
    label.textContent = name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.title = `移除${name}`;
    remove.addEventListener("click", () => onRemove(name));
    token.append(label, remove);
    root.append(token);
  });
}

function removeValue(key, value) {
  state[key] = state[key].filter((item) => item !== value);
  renderAll();
  persist();
}

function renderCounts() {
  const hasDraft = state.draftedGenerals.length > 0;
  const currentGenerals = state.stage === "initial" ? state.initialGenerals.length : state.stage === "support" && state.support.dirty
    ? state.draftedGenerals.length + Number(Boolean(state.support.baseGeneral))
    : state.generals.length || (hasDraft ? state.draftedGenerals.length : state.initialGenerals.length);
  const currentSkills = state.stage === "initial" ? state.initialSkills.length : state.stage === "support" && state.support.dirty
    ? state.draftedSkills.length + state.support.baseSkills.filter(Boolean).length + Number(state.support.kit === "purple" && Boolean(state.support.purpleSkill))
    : state.skills.length || (hasDraft ? state.draftedSkills.length : state.initialSkills.length);
  byId("generalCount").textContent = `${currentGenerals} / ${hasDraft ? "11" : "10"}`;
  byId("skillCount").textContent = `${currentSkills} / ${hasDraft ? (state.support.kit === "purple" ? "23" : "22") : "20"}`;
  const done = state.rounds.filter(isRoundComplete).length;
  byId("draftCount").textContent = `${done} / 6`;
  byId("initialHint").textContent = `武将 ${state.initialGenerals.length}/${INITIAL_GENERAL_COUNT} · 战法 ${state.initialSkills.length}/${INITIAL_SKILL_COUNT}`;
  byId("startDraft").disabled = false;
  updateAdvisorSummary();
}

function showStage(name, shouldPersist = true) {
  if (name === "support" && state.rounds.some((round) => !isRoundComplete(round))) return toast("请先完成或跳过六轮选秀。");
  if (name === "teams") prepareCurrentTeamPool();
  state.stage = name;
  document.querySelectorAll(".stage-panel").forEach((panel) => { panel.hidden = panel.id !== `${name}Stage`; });
  document.querySelectorAll(".stage-tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.stage === name));
  renderCounts();
  if (name === "draft") renderDraft();
  if (name === "support") renderSupport();
  if (name === "teams") renderTeams();
  if (shouldPersist) persist();
}

function prepareCurrentTeamPool() {
  const hasDraft = state.rounds.some((round) => round.accepted);
  const draftGenerals = hasDraft ? state.draftedGenerals : state.initialGenerals;
  const draftSkills = hasDraft ? state.draftedSkills : state.initialSkills;
  let generals = [...draftGenerals];
  let skills = [...draftSkills];

  if (state.stage === "teams" && state.generals.length) {
    generals = [...state.generals];
    skills = [...state.skills];
  } else if (state.stage === "support") {
    if (!state.support.dirty && state.generals.length) {
      generals = [...state.generals];
      skills = [...state.skills];
    } else {
      if (state.support.baseGeneral && generalByName(state.support.baseGeneral)) generals.push(state.support.baseGeneral);
      for (const name of state.support.baseSkills) if (name && skillByName(name)) skills.push(name);
      if (state.support.kit === "general" && state.support.transformed && generalByName(state.support.transformResult)) {
        const targetIndex = generals.indexOf(state.support.transformed);
        if (targetIndex >= 0 && !generals.includes(state.support.transformResult)) generals[targetIndex] = state.support.transformResult;
      }
      if (state.support.kit === "orange") {
        state.support.orangeSkills.forEach((target, index) => {
          const targetIndex = skills.indexOf(target);
          const result = state.support.orangeResults[index];
          if (targetIndex >= 0 && skillByName(result) && !skills.includes(result)) skills[targetIndex] = result;
        });
      }
      if (state.support.kit === "purple" && state.support.purpleSkill && skillByName(state.support.purpleSkill)) skills.push(state.support.purpleSkill);
    }
  }

  generals = [...new Set(generals.filter((name) => generalByName(name)))];
  skills = [...new Set(skills.filter((name) => skillByName(name)))];
  const samePool = state.plan
    && JSON.stringify(state.plan.poolGenerals || []) === JSON.stringify(generals)
    && JSON.stringify(state.plan.poolSkills || []) === JSON.stringify(skills);
  state.generals = generals;
  state.skills = skills;
  if (!samePool) state.plan = calculatePlan(generals, skills);
}

function returnToCurrentFlow() {
  if (!state.rounds.some(isRoundComplete)) return showStage("initial");
  if (state.rounds.some((round) => !isRoundComplete(round))) return showStage("draft");
  showStage("support");
}

function beginDraft() {
  if (!state.draftedGenerals.length && !state.draftedSkills.length && !state.rounds.some(isRoundComplete)) {
    state.draftedGenerals = [...state.initialGenerals];
    state.draftedSkills = [...state.initialSkills];
    state.generals = [...state.draftedGenerals];
    state.skills = [...state.draftedSkills];
  }
  const next = nextDraftIndex();
  state.draftIndex = next >= 0 ? next : 5;
  showStage("draft");
  renderAll();
}

function currentRound() { return state.rounds[state.draftIndex]; }
function isRoundComplete(round) { return Boolean(round.accepted || round.skipped); }
function nextDraftIndex() { return state.rounds.findIndex((round) => !isRoundComplete(round)); }
function roundKindLabel(kind) { return kind === "general" ? "武将" : "战法"; }
function candidateCatalog(kind) { return kind === "general" ? "generalCatalog" : "skillCatalog"; }

function renderDraft() {
  if (!state.generals.length && state.initialGenerals.length) state.generals = [...state.initialGenerals];
  if (!state.skills.length && state.initialSkills.length) state.skills = [...state.initialSkills];
  const round = currentRound();
  if (!round) return;
  const kind = round.kind;
  byId("roundEyebrow").textContent = `第 ${state.draftIndex + 1} 轮 · ${roundKindLabel(kind)}`;
  byId("roundTitle").textContent = round.directEntry ? `登记游戏中已选的${roundKindLabel(kind)}` : `选择一组${roundKindLabel(kind)}候选`;
  byId("draftModeHint").textContent = round.directEntry
    ? `只录入你在游戏里实际选中的 3 个${roundKindLabel(kind)}，无需回忆未选候选组。`
    : "录入三组候选供 agent 比较；如果已经在游戏中选完，也可以直接登记实际结果。";
  byId("toggleDirectEntry").textContent = round.directEntry ? "改为比较候选组" : "游戏中已选，登记结果";
  byId("toggleDirectEntry").disabled = isRoundComplete(round);
  byId("skipDraft").disabled = isRoundComplete(round);
  renderDraftProgress();
  renderDraftHistory();

  const container = byId("draftGroups");
  container.classList.toggle("is-direct-entry", round.directEntry);
  container.replaceChildren();
  if (round.directEntry) {
    const fields = document.createElement("div");
    fields.className = "direct-result-fields";
    for (let index = 0; index < 3; index += 1) {
      const input = document.createElement("input");
      input.setAttribute("list", candidateCatalog(kind));
      input.autocomplete = "off";
      input.placeholder = `游戏中选到的${roundKindLabel(kind)} ${index + 1}`;
      input.value = round.recordedGroup[index] || "";
      input.addEventListener("input", () => {
        round.recordedGroup[index] = input.value.trim();
        updateDraftRecommendation();
        persist();
      });
      fields.append(input);
    }
    container.append(fields);
  } else {
    round.groups.forEach((group, groupIndex) => {
      const card = document.createElement("article");
      card.className = `draft-group${(recommendedGroupIndex(round) === groupIndex) ? " is-recommended" : ""}`;
      const head = document.createElement("div");
      head.className = "draft-group-head";
      const title = document.createElement("strong");
      title.textContent = `候选组 ${groupIndex + 1}`;
      const score = document.createElement("span");
      const groupNames = Array.from({ length: 3 }, (_, index) => group[index] || "");
      const groupComplete = groupNames.every(Boolean);
      const scored = scoreDraftGroup(kind, groupNames);
      const recommendedIndex = recommendedGroupIndex(round);
      score.textContent = `${groupComplete ? `协同分 ${scored.score.toFixed(1)}` : "待录入"}${groupIndex === recommendedIndex ? " · 建议" : ""}${round.selected === groupIndex ? " · 已选" : ""}`;
      head.append(title, score);
      const fields = document.createElement("div");
      fields.className = "candidate-fields";
      for (let candidateIndex = 0; candidateIndex < 3; candidateIndex += 1) {
        const input = document.createElement("input");
        input.setAttribute("list", candidateCatalog(kind));
        input.autocomplete = "off";
        input.placeholder = `${roundKindLabel(kind)} ${candidateIndex + 1}`;
        input.value = group[candidateIndex] || "";
        input.addEventListener("input", () => {
          round.groups[groupIndex][candidateIndex] = input.value.trim();
          updateDraftRecommendation();
          persist();
        });
        fields.append(input);
      }
      const rationale = document.createElement("p");
      rationale.className = "group-score";
      rationale.textContent = groupComplete ? scored.reason : "录入游戏展示的三个候选后，查看本组协同评分。";
      if (round.selected === groupIndex) card.classList.add("is-selected");
      card.append(head, fields, rationale);
      card.addEventListener("click", (event) => {
        if (event.target.matches("input") || isRoundComplete(round)) return;
        round.selected = groupIndex;
        byId("acceptDraft").disabled = !groupValid(kind, group);
        container.querySelectorAll(".draft-group").forEach((item, index) => item.classList.toggle("is-selected", index === groupIndex));
        updateDraftRecommendation();
        persist();
      });
      container.append(card);
    });
  }
  updateDraftRecommendation();
}

function renderDraftProgress() {
  byId("draftProgress").replaceChildren(...state.rounds.map((entry, index) => {
    const segment = document.createElement("div");
    const status = entry.skipped ? "已跳过" : entry.accepted ? (entry.directEntry ? "已登记" : `已选第${Number(entry.selected) + 1}组`) : index === state.draftIndex ? "当前轮" : "待处理";
    segment.className = `progress-segment${isRoundComplete(entry) ? " is-done" : ""}${entry.skipped ? " is-skipped" : ""}${index === state.draftIndex ? " is-current" : ""}`;
    const number = document.createElement("strong");
    number.textContent = `第 ${index + 1} 轮`;
    const label = document.createElement("span");
    label.textContent = `${roundKindLabel(entry.kind)} · ${status}`;
    segment.append(number, label);
    return segment;
  }));
}

function renderDraftHistory() {
  const root = byId("draftHistory");
  root.replaceChildren();
  state.rounds.forEach((round, index) => {
    if (!isRoundComplete(round)) return;
    const row = document.createElement("div");
    row.className = `draft-history-item${round.skipped ? " is-skipped" : ""}`;
    const title = document.createElement("strong");
    title.textContent = `第 ${index + 1} 轮 · ${roundKindLabel(round.kind)}`;
    const detail = document.createElement("span");
    detail.textContent = round.skipped
      ? "已跳过，未加入本局卡池"
      : round.directEntry
        ? `按游戏已选结果录入：${round.recordedGroup.join("、")}`
        : `已选候选组 ${Number(round.selected) + 1}：${(round.groups[round.selected] || []).join("、")}`;
    row.append(title, detail);
    root.append(row);
  });
}

function toggleDirectEntry() {
  const round = currentRound();
  if (!round || isRoundComplete(round)) return;
  round.directEntry = !round.directEntry;
  renderDraft();
  persist();
}

function skipDraftRound() {
  const round = currentRound();
  if (!round || isRoundComplete(round)) return;
  round.skipped = true;
  round.accepted = false;
  round.selected = null;
  advanceDraft();
}

function recordedGroupValid(round) {
  const names = round.recordedGroup.map((name) => name.trim());
  if (names.length !== 3 || names.some((name) => !name) || new Set(names).size !== 3) return false;
  if (round.kind === "general") return names.every((name) => generalByName(name) && !state.generals.includes(name));
  return names.every((name) => skillByName(name) && !state.skills.includes(name));
}

function groupValid(kind, group) {
  const names = Array.from({ length: 3 }, (_, index) => group[index] || "");
  if (names.some((name) => !name) || new Set(names).size !== 3) return false;
  if (kind === "general") return names.every((name) => generalByName(name) && !state.generals.includes(name));
  return names.every((name) => skillByName(name) && !state.skills.includes(name));
}

function recommendedGroupIndex(round) {
  const scores = round.groups.map((group) => groupValid(round.kind, group) ? scoreDraftGroup(round.kind, group).score : -Infinity);
  return scores.indexOf(Math.max(...scores));
}

function scoreDraftGroup(kind, names) {
  if (kind === "general") {
    const valid = names.map(generalByName).filter(Boolean);
    if (valid.length !== 3) return { score: 0, reason: "" };
    const base = valid.reduce((sum, general) => sum + generalPotential(general), 0);
    const roles = valid.flatMap(generalRoles);
    const roleDiversity = new Set(roles).size;
    const factions = new Set(valid.map((general) => general.faction).filter(Boolean)).size;
    const damage = valid.filter(isDamageGeneral).length;
    const support = valid.filter(isSupportGeneral).length;
    const score = base + roleDiversity * 1.8 + Math.min(damage, 2) * 1.2 + Math.min(support, 1) * 1.5 + factions * 0.35;
    const reasons = [];
    if (roleDiversity >= 3) reasons.push("角色覆盖较广");
    if (damage > 0 && support > 0) reasons.push("输出与辅助兼有");
    if (new Set(valid.map((general) => general.troop_type)).size > 1) reasons.push("兵种选择更灵活");
    return { score, reason: reasons.join("；") || "武将属性与自带战法综合评分" };
  }
  const valid = names.map(skillByName).filter(Boolean);
  if (valid.length !== 3) return { score: 0, reason: "" };
  const fits = valid.map((skill) => bestSkillFit(skill, state.generals));
  const tags = valid.flatMap(skillTags);
  const diversity = new Set(tags).size;
  const score = valid.reduce((sum, skill, index) => sum + skillBaseValue(skill) + fits[index].score, 0) + diversity * 1.15;
  const reasons = [...new Set(fits.map((fit) => fit.reason).filter(Boolean))].slice(0, 2);
  if (diversity >= 4) reasons.push("效果类型互补");
  return { score, reason: reasons.join("；") || "效果结构与现有武将适配评分" };
}

function updateDraftRecommendation() {
  const round = currentRound();
  if (!round) return;
  if (isRoundComplete(round)) {
    byId("draftRecommendation").textContent = round.skipped ? "本轮已跳过，没有向卡池加入新卡。" : "本轮结果已记录并加入卡池；可在上方查看已处理轮次。";
    byId("acceptDraft").textContent = "本轮已处理";
    byId("acceptDraft").disabled = true;
    return;
  }
  if (round.directEntry) {
    const valid = recordedGroupValid(round);
    byId("draftRecommendation").textContent = valid
      ? "已确认三张牌均存在于资料库且未重复。确认后会加入当前卡池，可随时切到“队伍编成”查看建议。"
      : `录入 3 个不同且未在卡池中的${roundKindLabel(round.kind)}名称。`;
    byId("acceptDraft").textContent = "确认游戏中已选结果 →";
    byId("acceptDraft").disabled = !valid;
    return;
  }
  const bestIndex = recommendedGroupIndex(round);
  const group = round.groups[bestIndex];
  const recommendation = byId("draftRecommendation");
  if (!group || !Array.from({ length: 3 }, (_, index) => group[index] || "").every(Boolean) || bestIndex < 0) {
    recommendation.textContent = "录入三组候选后，系统会按武将/战法数据给出协同评分与推荐组。";
    byId("acceptDraft").disabled = true;
    return;
  }
  const scored = scoreDraftGroup(round.kind, group);
  const selectedValid = Number.isInteger(round.selected) && groupValid(round.kind, round.groups[round.selected]);
  recommendation.innerHTML = `<strong>当前推荐：候选组 ${bestIndex + 1}</strong> · ${escapeHtml(scored.reason)}。这是协同启发式评分，不是实测胜率。`;
  byId("acceptDraft").textContent = round.selected === null ? `采用推荐组 ${bestIndex + 1} →` : `确认候选组 ${round.selected + 1} →`;
  byId("acceptDraft").disabled = round.selected === null ? !groupValid(round.kind, group) : !selectedValid;
}

function acceptDraftGroup() {
  const round = currentRound();
  if (isRoundComplete(round)) return;
  if (round.directEntry) {
    if (!recordedGroupValid(round)) return toast(`请录入 3 个不同且未重复的有效${roundKindLabel(round.kind)}。`);
    round.recordedGroup = round.recordedGroup.map((name) => name.trim());
    round.accepted = true;
    if (round.kind === "general") state.draftedGenerals.push(...round.recordedGroup);
    else state.draftedSkills.push(...round.recordedGroup);
    state.generals = [...state.draftedGenerals];
    state.skills = [...state.draftedSkills];
    advanceDraft();
    return;
  }
  const selected = round.selected === null ? recommendedGroupIndex(round) : round.selected;
  const group = round.groups[selected];
  if (!groupValid(round.kind, group)) return toast("请确认所选组的三个名字均来自资料库，且未重复。" + (round.kind === "general" ? "武将不能重复入队。" : "战法不能重复入池。"));
  round.selected = selected;
  round.accepted = true;
  if (round.kind === "general") state.draftedGenerals.push(...group);
  else state.draftedSkills.push(...group);
  state.generals = [...state.draftedGenerals];
  state.skills = [...state.draftedSkills];
  advanceDraft();
}

function advanceDraft() {
  const next = nextDraftIndex();
  if (next < 0) showStage("support");
  else state.draftIndex = next;
  renderAll();
  persist();
}

function renderSupport() {
  renderTokens("ownedGenerals", state.ownedGenerals, (name) => removeValue("ownedGenerals", name));
  renderTokens("ownedSkills", state.ownedSkills, (name) => removeValue("ownedSkills", name));
  fillSelect(byId("baseGeneralSupport"), state.ownedGenerals, state.support.baseGeneral, "选择账号武将");
  fillSelect(byId("baseSkillSupport1"), state.ownedSkills, state.support.baseSkills[0], "选择账号战法");
  fillSelect(byId("baseSkillSupport2"), state.ownedSkills, state.support.baseSkills[1], "选择账号战法");
  byId("baseGeneralSupport").onchange = (event) => { state.support.baseGeneral = event.target.value; state.support.dirty = true; persist(); };
  byId("baseSkillSupport1").onchange = (event) => { state.support.baseSkills[0] = event.target.value; state.support.dirty = true; persist(); };
  byId("baseSkillSupport2").onchange = (event) => { state.support.baseSkills[1] = event.target.value; state.support.dirty = true; persist(); };
  byId("kitType").value = state.support.kit;
  byId("kitType").onchange = () => { state.support.kit = byId("kitType").value; renderKitDetails(); renderCounts(); persist(); };
  renderGeneralSupportAdvice();
  renderKitDetails();
}

function fillSelect(select, values, selected, placeholder) {
  select.replaceChildren(new Option(placeholder, ""));
  values.forEach((value) => select.append(new Option(value, value)));
  select.value = values.includes(selected) ? selected : "";
}

function renderGeneralSupportAdvice() {
  if (!byId("generalSupportAdvice")) return;
  const category = byId("transformCategory")?.value || state.support.transformCategory;
  const target = state.support.transformed || byId("transformTarget")?.value;
  const distribution = state.draftedGenerals.map(generalByName).filter(Boolean);
  const counts = {
    physical: distribution.filter((general) => classifyGeneral(general) === "physical").length,
    strategy: distribution.filter((general) => classifyGeneral(general) === "strategy").length,
    support: distribution.filter((general) => classifyGeneral(general) === "support").length,
  };
  const labels = { physical: "兵刃输出", strategy: "谋略输出", support: "辅助" };
  const sorted = Object.keys(counts).sort((a, b) => counts[a] - counts[b]);
  const advice = sorted[0] === category ? "该方向可以补足当前队伍池相对薄弱的定位。" : `当前较缺少“${labels[sorted[0]]}”类型，可比较是否改选该方向。`;
  byId("generalSupportAdvice").textContent = `${target ? `待转化：${target}。` : "先选择一个已有武将。"} 当前大致构成：兵刃输出 ${counts.physical}、谋略输出 ${counts.strategy}、辅助 ${counts.support}。${advice}`;
}

function renderKitDetails() {
  const root = byId("kitDetails");
  const type = byId("kitType").value || state.support.kit;
  state.support.kit = type;
  if (type === "none") { root.replaceChildren(); persist(); return; }
  if (type === "general") {
    root.innerHTML = `<label class="field-label">待转化武将<select id="transformTarget"></select></label><label class="field-label">转化定位<select id="transformCategory"><option value="physical">兵刃输出</option><option value="strategy">谋略输出</option><option value="support">辅助</option></select></label><div id="generalSupportAdvice" class="support-advice"></div><label class="field-label">游戏生成结果<input id="transformResult" list="generalCatalog" autocomplete="off" placeholder="搜索并记录实际结果" /></label>`;
    fillSelect(byId("transformTarget"), state.draftedGenerals, state.support.transformed, "选择待转化武将");
    byId("transformTarget").onchange = (event) => { state.support.transformed = event.target.value; state.support.dirty = true; renderGeneralSupportAdvice(); persist(); };
    byId("transformCategory").value = state.support.transformCategory;
    byId("transformCategory").onchange = (event) => { state.support.transformCategory = event.target.value; state.support.dirty = true; renderGeneralSupportAdvice(); persist(); };
    byId("transformResult").value = state.support.transformResult;
    byId("transformResult").oninput = (event) => { state.support.transformResult = event.target.value.trim(); state.support.dirty = true; persist(); };
    renderGeneralSupportAdvice();
  } else if (type === "orange") {
    root.innerHTML = `<label class="field-label">橙色战法 1<select id="orangeSkill1"></select></label><label class="field-label">橙色战法 2<select id="orangeSkill2"></select></label><label class="field-label">转化类别<select id="orangeCategory"><option value="weapon">兵刃战法</option><option value="strategy">谋略战法</option><option value="chase">追击战法</option></select></label><label class="field-label">游戏生成结果 1<input id="orangeResult1" list="skillCatalog" autocomplete="off" /></label><label class="field-label">游戏生成结果 2<input id="orangeResult2" list="skillCatalog" autocomplete="off" /></label>`;
    fillSelect(byId("orangeSkill1"), state.draftedSkills, state.support.orangeSkills[0], "选择已获得战法");
    fillSelect(byId("orangeSkill2"), state.draftedSkills, state.support.orangeSkills[1], "选择已获得战法");
    byId("orangeSkill1").onchange = (event) => { state.support.orangeSkills[0] = event.target.value; state.support.dirty = true; persist(); };
    byId("orangeSkill2").onchange = (event) => { state.support.orangeSkills[1] = event.target.value; state.support.dirty = true; persist(); };
    byId("orangeCategory").value = state.support.orangeCategory;
    byId("orangeCategory").onchange = (event) => { state.support.orangeCategory = event.target.value; state.support.dirty = true; persist(); };
    [1, 2].forEach((number) => {
      const input = byId(`orangeResult${number}`);
      input.value = state.support.orangeResults[number - 1];
      input.oninput = (event) => { state.support.orangeResults[number - 1] = event.target.value.trim(); state.support.dirty = true; persist(); };
    });
  } else if (type === "purple") {
    root.innerHTML = `<label class="field-label">额外紫色战法支援<select id="purpleSupportSkill"></select></label>`;
    fillSelect(byId("purpleSupportSkill"), state.ownedSkills, state.support.purpleSkill, "选择账号已拥有战法");
    byId("purpleSupportSkill").onchange = (event) => { state.support.purpleSkill = event.target.value; state.support.dirty = true; persist(); };
  }
  persist();
}

function finishSupport() {
  const selectedBaseGeneral = byId("baseGeneralSupport").value;
  const baseSkill1 = byId("baseSkillSupport1").value;
  const baseSkill2 = byId("baseSkillSupport2").value;
  if (!selectedBaseGeneral || !baseSkill1 || !baseSkill2) return toast("请从账号库存完成基础的 1 个武将和 2 个战法支援位。");
  state.support.baseGeneral = selectedBaseGeneral;
  state.support.baseSkills = [baseSkill1, baseSkill2];
  if (baseSkill1 === baseSkill2) return toast("两个基础战法支援位不能选择同一个战法。");

  const generals = [...state.draftedGenerals, selectedBaseGeneral];
  const skills = [...state.draftedSkills, baseSkill1, baseSkill2];
  if (new Set(generals).size !== generals.length) return toast("支援武将已经在本局卡池中，请更换账号武将。");
  if (new Set(skills).size !== skills.length) return toast("支援战法已经在本局卡池中，请更换账号战法。");

  if (state.support.kit === "general") {
    const target = state.support.transformed || byId("transformTarget")?.value;
    const result = (byId("transformResult")?.value || state.support.transformResult).trim();
    if (!target || !generalByName(result)) return toast("请指定待转化武将，并录入游戏实际生成的新武将。");
    if (generals.includes(result) && result !== target) return toast("转化结果已在卡池中，请核对游戏结果。");
    generals[generals.indexOf(target)] = result;
  } else if (state.support.kit === "orange") {
    const targets = state.support.orangeSkills;
    const results = state.support.orangeResults.map((value) => value.trim());
    if (!targets.every(Boolean) || targets[0] === targets[1] || !results.every((name) => skillByName(name)) || results[0] === results[1]) return toast("请选择两个不同战法，并准确录入两项游戏生成结果。");
    if (targets.some((name) => !state.draftedSkills.includes(name))) return toast("重随机目标必须来自本局选秀获得的战法。");
    targets.forEach((name, index) => { skills[skills.indexOf(name)] = results[index]; });
    if (new Set(skills).size !== skills.length) return toast("重随机后的战法出现重复，请核对实际结果。");
  } else if (state.support.kit === "purple") {
    const result = byId("purpleSupportSkill")?.value || state.support.purpleSkill;
    if (!result || !state.ownedSkills.includes(result)) return toast("请选择账号库存中的额外紫色战法。");
    if (skills.includes(result)) return toast("该战法已在本局卡池中，不能重复加入。");
    skills.push(result);
  }

  state.generals = generals;
  state.skills = skills;
  state.plan = calculatePlan(generals, skills);
  if (!state.plan) return toast("当前资料不足以完成三队编成，请检查武将与战法卡池。 ");
  state.support.dirty = false;
  showStage("teams");
  renderCounts();
  renderTeams();
  persist();
}

function calculatePlan(generalNames, skillNames) {
  const roster = [...new Set(generalNames)].map(generalByName).filter(Boolean);
  const tactics = [...new Set(skillNames)].map(skillByName).filter(Boolean);
  if (!roster.length) return null;
  const activeCount = roster.length < 3 ? roster.length : Math.min(9, Math.floor(roster.length / 3) * 3);
  const subsets = roster.length === activeCount
    ? [roster]
    : combinations(roster.length, activeCount).map((indices) => indices.map((index) => roster[index]));
  let best = null;
  for (const active of subsets) {
    const partitions = [];
    partitionTeams(active, [], partitions);
    for (const teams of partitions) {
      const score = teams.reduce((sum, group) => sum + teamScore(group), 0);
      if (!best || score > best.score) best = { teams, score };
    }
  }
  if (!best) return null;
  const assignments = best.teams.map((group) => group.map((general) => ({ general, skills: [] })));
  const used = new Set();
  const skillSlotCount = assignments.reduce((sum, team) => sum + team.length * 2, 0);
  for (let slot = 0; slot < skillSlotCount; slot += 1) {
    let pick = null;
    for (const team of assignments) {
      for (const member of team) {
        if (member.skills.length >= 2) continue;
        for (const skill of tactics) {
          if (used.has(skill.name)) continue;
          const fit = skillFit(skill, member.general, member.skills);
          if (!pick || fit.score > pick.fit.score) pick = { member, skill, fit };
        }
      }
    }
    if (!pick) break;
    pick.member.skills.push(pick.skill);
    used.add(pick.skill.name);
  }
  return {
    score: best.score,
    poolGenerals: roster.map((general) => general.name),
    poolSkills: tactics.map((skill) => skill.name),
    teams: assignments.map((team, index) => ({
      name: `第 ${index + 1} 队`,
      formation: recommendFormation(team),
      members: team.map((member) => ({ name: member.general.name, skills: member.skills.map((skill) => skill.name) })),
    })),
    reserve: roster.filter((general) => !best.teams.flat().some((chosen) => chosen.name === general.name)).map((general) => general.name),
    unassignedSkills: tactics.filter((skill) => !used.has(skill.name)).map((skill) => skill.name),
  };
}

function combinations(length, size, start = 0, prefix = [], output = []) {
  if (prefix.length === size) { output.push([...prefix]); return output; }
  for (let index = start; index <= length - (size - prefix.length); index += 1) {
    prefix.push(index);
    combinations(length, size, index + 1, prefix, output);
    prefix.pop();
  }
  return output;
}

function partitionTeams(roster, groups, output) {
  if (roster.length <= 3) { output.push([...groups, roster]); return; }
  const anchor = roster[0];
  for (const pair of combinations(roster.length - 1, 2)) {
    const group = [anchor, ...pair.map((index) => roster[index + 1])];
    const used = new Set(group.map((general) => general.name));
    partitionTeams(roster.filter((general) => !used.has(general.name)), [...groups, group], output);
  }
}

function teamScore(team) {
  const roles = team.flatMap(generalRoles);
  const uniqueRoles = new Set(roles);
  const damageCount = team.filter(isDamageGeneral).length;
  const supportCount = team.filter(isSupportGeneral).length;
  const factionCounts = countBy(team, (general) => general.faction);
  const troopCounts = countBy(team, (general) => general.troop_type);
  const sameFaction = Object.values(factionCounts).sort((a, b) => b - a)[0] || 0;
  const topTroop = Object.entries(troopCounts).sort((a, b) => b[1] - a[1])[0];
  const sameTroop = topTroop?.[1] || 0;
  let score = team.reduce((sum, general) => sum + generalPotential(general), 0);
  score += uniqueRoles.size * 2.2 + Math.min(damageCount, 2) * 1.8 + Math.min(supportCount, 1) * 2.0;
  const factionBonus = sameFaction >= 3 ? 0.10 : sameFaction === 2 ? 0.05 : 0;
  const teamAttributeTotal = team.reduce((sum, general) => sum + Object.values(general.stats || {}).reduce((statSum, stat) => statSum + (stat.current || 0) + (stat.growth || 0) * 45, 0), 0);
  score += teamAttributeTotal * factionBonus * 0.004;
  const troopBonus = troopEffect(topTroop?.[0], sameTroop);
  score += (troopBonus.offense + troopBonus.defense) * 30;
  if (damageCount === 0) score -= 10;
  else if (damageCount === 1) score -= 2.5;
  if (damageCount === 3) score -= 1.5;
  if (supportCount === 0) score -= 4;
  if (supportCount === 3) score -= 2;
  const innateTags = team.flatMap((general) => skillTags(skillByName(general.innate_skill) || {}));
  score += new Set(innateTags).size * 0.55;
  return score;
}

function recommendFormation(team) {
  const frontline = team.filter((general) => generalRoles(general).includes("前排")).length;
  const physical = team.filter((general) => classifyGeneral(general) === "physical").length;
  const strategy = team.filter((general) => classifyGeneral(general) === "strategy").length;
  if (frontline === 1 && physical + strategy >= 2) return "箕形阵";
  if (frontline >= 2 && team.some(isSupportGeneral)) return "雁形阵";
  if (physical >= 2) return "锥形阵";
  if (strategy >= 2) return "鱼鳞阵";
  return "方圆阵";
}

function troopEffect(troopType, count) {
  const full = count >= 3;
  const pair = count === 2;
  if (!full && !pair) return { offense: 0, defense: 0 };
  const values = {
    "盾兵": { offense: 0, defense: full ? 0.05 : 0.035 },
    "弓兵": { offense: full ? 0.05 : 0.035, defense: 0 },
    "枪兵": { offense: full ? 0.03 : 0.021, defense: full ? 0.02 : 0.014 },
    "骑兵": { offense: full ? 0.02 : 0.014, defense: full ? 0.03 : 0.021 },
  };
  return values[troopType] || { offense: 0, defense: 0 };
}

function renderTeams() {
  if (!state.plan) {
    byId("recommendedTeams").innerHTML = '<p class="empty-state">当前还没有可用武将。录入初始卡池后，这里会随时生成阶段性编成建议。</p>';
    byId("teamSummary").textContent = "等待录入武将";
    return;
  }
  const root = byId("recommendedTeams");
  root.replaceChildren();
  root.dataset.teamCount = String(state.plan.teams.length);
  const allGenerals = state.generals.map(generalByName).filter(Boolean);
  const allSkills = state.skills.map(skillByName).filter(Boolean);
  state.plan.teams.forEach((team, teamIndex) => {
    const card = document.createElement("article");
    card.className = "recommended-team";
    const head = document.createElement("div");
    head.className = "recommended-team-head";
    const title = document.createElement("h3");
    title.textContent = team.name;
    const score = document.createElement("div");
    score.className = "team-score";
    const formationSelect = document.createElement("select");
    formationSelect.className = "formation-choice";
    ["一字阵", "箕形阵", "雁形阵", "方圆阵", "锥形阵", "钩形阵", "偃月阵", "鱼鳞阵"].forEach((formation) => formationSelect.append(new Option(formation, formation)));
    formationSelect.value = team.formation;
    formationSelect.setAttribute("aria-label", `${team.name}阵型`);
    formationSelect.addEventListener("change", () => { team.formation = formationSelect.value; persist(); });
    score.append(formationSelect);
    head.append(title, score);
    card.append(head);
    team.members.forEach((member, memberIndex) => {
      const section = document.createElement("section");
      section.className = "team-member";
      const heading = document.createElement("div");
      heading.className = "member-heading";
      const generalSelect = document.createElement("select");
      const otherGeneralNames = state.plan.teams.flatMap((otherTeam, otherTeamIndex) => otherTeam.members.filter((_, index) => otherTeamIndex !== teamIndex || index !== memberIndex).map((item) => item.name));
      const availableGenerals = allGenerals.map((general) => general.name).filter((name) => name === member.name || !otherGeneralNames.includes(name));
      fillSelect(generalSelect, availableGenerals, member.name, "选择武将");
      generalSelect.addEventListener("change", () => {
        if (otherGeneralNames.includes(generalSelect.value)) return toast("一名武将不能同时编入两队。");
        member.name = generalSelect.value;
        rerankTeam(teamIndex);
      });
      heading.append(generalSelect);
      const general = generalByName(member.name);
      const meta = document.createElement("p");
      meta.className = "member-meta";
      meta.textContent = general ? `${general.faction || ""} · ${general.troop_type || ""} · ${(general.roles || []).join(" / ")}` : "";
      const skillControls = document.createElement("div");
      skillControls.className = "member-skills";
      for (let skillIndex = 0; skillIndex < 2; skillIndex += 1) {
        const select = document.createElement("select");
        const current = member.skills[skillIndex] || "";
        const usedElsewhere = state.plan.teams.flatMap((otherTeam) => otherTeam.members.flatMap((otherMember) => otherMember.skills.filter((name) => name && !(otherMember === member && otherMember.skills.indexOf(name) === skillIndex))));
        const available = allSkills.map((skill) => skill.name).filter((name) => name === current || !usedElsewhere.includes(name));
        fillSelect(select, available, current, `携带战法 ${skillIndex + 1}`);
        select.addEventListener("change", () => {
          if (usedElsewhere.includes(select.value)) return toast("战法不能重复分配给不同武将。");
          member.skills[skillIndex] = select.value;
          renderTeams();
          persist();
        });
        skillControls.append(select);
      }
      section.append(heading, meta, skillControls);
      card.append(section);
    });
    const traits = document.createElement("p");
    traits.className = "team-traits";
    traits.textContent = teamReasons(team.members.map((member) => generalByName(member.name)).filter(Boolean));
    card.append(traits);
    root.append(card);
  });
  const assigned = state.plan.teams.flatMap((team) => team.members.flatMap((member) => member.skills)).filter(Boolean);
  const duplicateSkill = assigned.length !== new Set(assigned).size;
  const validMembers = state.plan.teams.flatMap((team) => team.members.map((member) => member.name));
  const duplicateGeneral = validMembers.length !== new Set(validMembers).size;
  const memberCount = validMembers.length;
  const skillSlotCount = memberCount * 2;
  const underfilledTeams = state.plan.teams.some((team) => team.members.length < 3);
  byId("teamSummary").textContent = `当前推荐 ${state.plan.teams.length} 队，使用 ${memberCount} / ${state.generals.length} 名武将，${assigned.length} / ${skillSlotCount} 个战法位已配置${state.plan.reserve.length ? ` · 暂留武将：${state.plan.reserve.join("、")}` : ""}${state.plan.unassignedSkills.length ? ` · 暂留战法：${state.plan.unassignedSkills.join("、")}` : ""}${underfilledTeams ? " · 队伍人数未满，补充卡池后可重新计算" : ""}${duplicateSkill || duplicateGeneral ? " · 存在重复分配，请检查" : ""}`;
}

function rerankTeam(teamIndex) {
  const team = state.plan.teams[teamIndex];
  const members = team.members.map((member) => generalByName(member.name)).filter(Boolean);
  team.formation = recommendFormation(members);
  renderTeams();
  persist();
}

function teamReasons(team) {
  const counts = countBy(team, (general) => general.faction);
  const troopCounts = countBy(team, (general) => general.troop_type);
  const faction = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  const troop = Object.entries(troopCounts).sort((a, b) => b[1] - a[1])[0];
  const roles = [...new Set(team.flatMap(generalRoles))];
  const notes = [];
  if (faction && faction[1] >= 2) notes.push(`${faction[0]}阵营 ${faction[1]} 人，全属性 +${faction[1] >= 3 ? 10 : 5}%`);
  if (troop && troop[1] >= 2) {
    const bonus = troopEffect(troop[0], troop[1]);
    const effects = [bonus.offense ? `造成伤害 +${Number((bonus.offense * 100).toFixed(1))}%` : "", bonus.defense ? `受到伤害 -${Number((bonus.defense * 100).toFixed(1))}%` : ""].filter(Boolean).join("，");
    notes.push(`${troop[0]} ${troop[1]} 人${effects ? `，${effects}` : ""}`);
  }
  if (roles.length) notes.push(`定位：${roles.join("、")}`);
  return notes.join(" · ");
}

function copyRoster() {
  if (!state.plan) return;
  const lines = state.plan.teams.map((team) => `${team.name}（${team.formation}）：\n${team.members.map((member) => `- ${member.name}：${member.skills.join("、") || "待配置战法"}`).join("\n")}`).join("\n\n");
  const text = `${lines}\n\n预留武将：${state.plan.reserve.join("、") || "无"}`;
  navigator.clipboard.writeText(text).then(() => toast("三队编成摘要已复制。"), () => toast("复制失败，请检查浏览器剪贴板权限。"));
}

function resetArena() {
  if (!window.confirm("清空当前演武记录？此操作会删除本地保存的选秀与编成。")) return;
  localStorage.removeItem(STORAGE_KEY);
  window.location.reload();
}

function generalPotential(general) {
  const stats = Object.fromEntries(Object.entries(general.stats || {}).map(([key, value]) => [key, (value.current || 0) + (value.growth || 0) * 45]));
  const max = Math.max(...Object.values(stats), 0);
  const roles = generalRoles(general);
  let score = max * 0.035 + Object.values(stats).reduce((sum, value) => sum + value, 0) * 0.006;
  if (roles.includes("输出")) score += 3;
  if (roles.includes("辅助")) score += 2;
  if (roles.includes("治疗")) score += 2;
  if (roles.includes("前排")) score += 1;
  const innate = skillByName(general.innate_skill);
  if (innate) score += skillBaseValue(innate) * 0.28;
  return score;
}

function generalRoles(general) {
  return (general.roles || []).flatMap((role) => ["输出", "治疗", "辅助", "防御", "前排", "控制", "均衡"].filter((known) => role.includes(known)));
}

function classifyGeneral(general) {
  const innate = skillByName(general.innate_skill);
  const tags = skillTags(innate || {});
  const stats = general.stats || {};
  const roles = generalRoles(general);
  if (tags.includes("兵刃") || tags.includes("谋略")) {
    if (tags.includes("兵刃") && tags.includes("谋略")) return (stats.force?.current || 0) >= (stats.intellect?.current || 0) ? "physical" : "strategy";
    return tags.includes("兵刃") ? "physical" : "strategy";
  }
  if (roles.includes("输出")) return (stats.force?.current || 0) >= (stats.intellect?.current || 0) ? "physical" : "strategy";
  if (roles.some((role) => ["治疗", "辅助", "防御"].includes(role))) return "support";
  return (stats.force?.current || 0) >= (stats.intellect?.current || 0) ? "physical" : "strategy";
}

function isDamageGeneral(general) {
  return classifyGeneral(general) !== "support";
}

function isSupportGeneral(general) {
  return classifyGeneral(general) === "support";
}

function bestSkillFit(skill, roster) {
  const fits = roster.map((name) => {
    const general = typeof name === "string" ? generalByName(name) : name;
    return general ? skillFit(skill, general, []).score : 0;
  }).sort((a, b) => b - a);
  return { score: fits[0] || 0, reason: fits[0] ? "至少有一名武将适配" : "" };
}

function skillFit(skill, general, existing = []) {
  const tags = skillTags(skill);
  const stats = general.stats || {};
  const force = (stats.force?.current || 0) + (stats.force?.growth || 0) * 45;
  const intellect = (stats.intellect?.current || 0) + (stats.intellect?.growth || 0) * 45;
  const effects = (skill.effects || []).flatMap((effect) => Array.isArray(effect) ? effect : [effect]);
  const scales = new Set(effects.flatMap((effect) => effect.scales_with || []));
  let score = skillBaseValue(skill);
  const reasons = [];
  if (tags.includes("兵刃")) { score += force * 0.012; reasons.push("武力适配"); }
  if (tags.includes("谋略")) { score += intellect * 0.012; reasons.push("智力适配"); }
  if (scales.has("武力")) score += force * 0.008;
  if (scales.has("智力")) score += intellect * 0.008;
  if (scales.has("统率")) score += (((stats.command?.current || 0) + (stats.command?.growth || 0) * 45) * 0.004);
  if (tags.includes("治疗") && isSupportGeneral(general)) { score += 3; reasons.push("辅助/治疗定位适配"); }
  if (tags.includes("输出") && isDamageGeneral(general)) { score += 2.4; reasons.push("输出定位适配"); }
  if (skill.type === "指挥" || skill.type === "被动") score += 1.2;
  if (["主动", "追击"].includes(skill.type)) score += (skill.activation_rate || 0) * 1.1;
  if (existing.length) {
    const overlap = skillTags(existing.map(skillByName).filter(Boolean).reduce((acc, item) => ({ traits: [...(acc.traits || []), ...(item.traits || [])], effects: [...(acc.effects || []), ...(item.effects || [])] }), {})).filter((tag) => tags.includes(tag)).length;
    score += Math.max(-2, 1.4 - overlap * 1.2);
  }
  return { score, reason: [...new Set(reasons)].join("、") };
}

function skillBaseValue(skill) {
  const weights = { "兵刃": 6.2, "谋略": 6.2, "治疗": 4.9, "防御": 4.8, "控制": 4.2, "增益": 3.3, "减益": 3.1, "辅助": 2.8 };
  const tags = skillTags(skill);
  const effects = (skill.effects || []).flatMap((effect) => Array.isArray(effect) ? effect : [effect]);
  let value = tags.reduce((sum, tag) => sum + (weights[tag] || 0), 0);
  value += Math.min(effects.length, 5) * 0.45;
  value += (skill.activation_rate || 0) * (skill.type === "主动" || skill.type === "追击" ? 1 : 0.25);
  if (skill.type === "指挥") value += 1;
  return value;
}

function skillTags(skill) {
  const tags = new Set(skill.traits || []);
  const effects = (skill.effects || []).flatMap((effect) => Array.isArray(effect) ? effect : [effect]);
  for (const effect of effects) {
    const kind = String(effect.kind || "");
    if (!/damage_taken/.test(kind) && /weapon_damage|weapon_and_strategy_damage|basic_attack|chase_damage|extra_weapon_damage/.test(kind)) tags.add("兵刃");
    if (!/damage_taken/.test(kind) && /strategy_damage/.test(kind)) tags.add("谋略");
    if (/heal|lifesteal|mutiny/.test(kind)) tags.add("治疗");
    if (/damage_taken_reduction|evasion|cover_damage|resist|armor/.test(kind)) tags.add("防御");
    if (/state|control|cannot_|disarm|silence/.test(kind)) tags.add("控制");
    if (/bonus|stat_|gain_stack|grant_state|insight/.test(kind)) tags.add("增益");
    if (/reduction|steal_stat|damage_taken_increase/.test(kind)) tags.add("减益");
  }
  return [...tags].map((tag) => {
    if (/兵刃/.test(tag)) return "兵刃";
    if (/谋略/.test(tag)) return "谋略";
    if (/治疗|恢复|回复/.test(tag)) return "治疗";
    if (/防御|减伤|抵御|规避/.test(tag)) return "防御";
    if (/控制|缴械|技穷|震慑|混乱/.test(tag)) return "控制";
    if (/增益|强化|加成/.test(tag)) return "增益";
    if (/减益|削弱|降低/.test(tag)) return "减益";
    if (/输出/.test(tag)) return "输出";
    if (/辅助/.test(tag)) return "辅助";
    return tag;
  });
}

function countBy(items, getter) {
  return items.reduce((counts, item) => { const key = getter(item); if (key) counts[key] = (counts[key] || 0) + 1; return counts; }, {});
}

function toast(message) {
  const element = byId("toast");
  element.textContent = message;
  element.classList.add("is-visible");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("is-visible"), 2600);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

initialize();
