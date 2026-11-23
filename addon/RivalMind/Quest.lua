-- RivalMind Quest Intelligence v0.2-alpha
-- Only ordinary quest events and the modern C_QuestLog API are used.
-- No quests are accepted, abandoned, tracked or navigated automatically.
-- No network calls or messages; no automatic UI.
local _, RM = ...
local MAX_EVENTS = 200
local knownTitles = {}
local knownComplete = {}
local recentEvents = {}
local scanPending = false

local function safeInteger(value)
    local ok, result = pcall(function()
        if type(value) ~= "number" or value ~= value then return nil end
        if value < 0 or value > 5000000000 then return nil end
        return math.floor(value)
    end)
    if ok then return result end
    return nil
end

local function questID(value)
    local num = safeInteger(value)
    if num and num > 0 and num < 100000000 then return num end
    return nil
end

local function safeString(value, length)
    local ok, result = pcall(function()
        if type(value) ~= "string" then return "" end
        if issecretvalue and issecretvalue(value) then return "" end
        return value:sub(1, length)
    end)
    return ok and result or ""
end

local function encode(value)
    return (safeString(value, 160):gsub("([^%w%-%._])", function(ch)
        return string.format("%%%02X", string.byte(ch))
    end))
end

local function getTitle(id)
    if knownTitles[id] then return knownTitles[id] end
    if type(C_QuestLog) ~= "table" or type(C_QuestLog.GetTitleForQuestID) ~= "function" then
        return ""
    end
    local ok, value = pcall(C_QuestLog.GetTitleForQuestID, id)
    if not ok then return "" end
    local title = safeString(value, 120)
    if title ~= "" then knownTitles[id] = title end
    return title
end

local function eventStore()
    if type(RivalMindDB) ~= "table" then return nil end
    if type(RivalMindDB.questEvents) ~= "table" then RivalMindDB.questEvents = {} end
    if type(RivalMindDB.nextQuestEventID) ~= "number" then RivalMindDB.nextQuestEventID = 0 end
    while #RivalMindDB.questEvents > MAX_EVENTS do
        table.remove(RivalMindDB.questEvents, 1)
    end
    return RivalMindDB.questEvents
end

local function record(kind, id, reward, title)
    id = questID(id)
    if not id then return end
    local records = eventStore()
    if not records then return end
    local timestamp = safeInteger(time()) or 0
    local key = kind .. ":" .. tostring(id)
    if recentEvents[key] and (timestamp - recentEvents[key]) >= 0
       and (timestamp - recentEvents[key]) <= 2 then
        return
    end
    recentEvents[key] = timestamp

    local entryID = math.floor(RivalMindDB.nextQuestEventID) + 1
    RivalMindDB.nextQuestEventID = entryID
    local name = safeString(title or getTitle(id), 120)
    local zone = ""
    local ok, zoneResult = pcall(GetZoneText)
    if ok then zone = safeString(zoneResult, 80) end
    local xp = safeInteger(reward)
    records[#records + 1] = {
        id = entryID, questID = id, stamp = timestamp,
        kind = kind, xpReward = xp, title = name, zone = zone,
    }
    while #records > MAX_EVENTS do table.remove(records, 1) end
end

local function scanQuestLog()
    scanPending = false
    if type(C_QuestLog) ~= "table" or type(C_QuestLog.GetNumQuestLogEntries) ~= "function"
       or type(C_QuestLog.GetInfo) ~= "function" then return end
    local ok, count = pcall(C_QuestLog.GetNumQuestLogEntries)
    if not ok or type(count) ~= "number" then return end
    count = math.min(math.max(math.floor(count), 0), 200)
    local found = {}
    for i = 1, count do
        local success, info = pcall(C_QuestLog.GetInfo, i)
        if success and type(info) == "table" then
            -- Access every quest-log field inside pcall: some Forever values can be secret.
            local fieldsOK, id, title, complete, header = pcall(function()
                return questID(info.questID), safeString(info.title, 120),
                    info.isComplete == true or info.isComplete == 1, info.isHeader == true
            end)
            if fieldsOK and id and not header then
                if title ~= "" then knownTitles[id] = title end
                if knownComplete[id] == false and complete then
                    record("C", id, nil, title)
                end
                knownComplete[id] = complete
                found[id] = true
            end
        end
    end
    for id in pairs(knownComplete) do
        if not found[id] then knownComplete[id] = nil end
    end
end

local function scheduleScan()
    if scanPending then return end
    scanPending = true
    if C_Timer and type(C_Timer.After) == "function" then
        C_Timer.After(0.6, scanQuestLog)
    else
        scanQuestLog()
    end
end

local function exportQuests()
    local records = eventStore()
    if not records then return end
    local lines = { "RQ1" }
    for _, entry in ipairs(records) do
        lines[#lines + 1] = table.concat({
            tostring(safeInteger(entry.id) or 0),
            tostring(safeInteger(entry.questID) or 0),
            tostring(safeInteger(entry.stamp) or 0),
            entry.kind == "A" and "A" or entry.kind == "C" and "C"
                or entry.kind == "T" and "T" or "R",
            entry.xpReward and tostring(safeInteger(entry.xpReward) or 0) or "",
            encode(entry.zone),
            encode(entry.title),
        }, ",")
    end
    RivalMindDB.questExport = table.concat(lines, ";")
end

function RM.PrintQuestStatus()
    local records = eventStore()
    if not records then
        print("|cff80c5ffRivalMind|r: Quest collection not initialized.")
        return
    end
    local last = records[#records]
    if not last then
        print("|cff80c5ffRivalMind|r: No quest events collected yet.")
        return
    end
    local labels = { A = "accepted", C = "objectives complete", T = "turned in", R = "removed (reason unknown)" }
    print(string.format("|cff80c5ffRivalMind|r: %d quest events saved (max %d). Latest: %s (%d), %s.",
        #records, MAX_EVENTS, last.title ~= "" and last.title or "Quest", last.questID,
        labels[last.kind] or "updated"))
end

local frame = CreateFrame("Frame")
local trackedEvents = {
    "PLAYER_ENTERING_WORLD", "QUEST_ACCEPTED", "QUEST_TURNED_IN",
    "QUEST_REMOVED", "QUEST_LOG_UPDATE", "PLAYER_LOGOUT",
}
for _, event in ipairs(trackedEvents) do
    pcall(frame.RegisterEvent, frame, event)
end

frame:SetScript("OnEvent", function(_, event, ...)
    if event == "PLAYER_ENTERING_WORLD" then
        eventStore()
        scheduleScan()
    elseif event == "QUEST_ACCEPTED" then
        local a, b = ...
        local id = questID(b) or questID(a)
        if id then record("A", id); scheduleScan() end
    elseif event == "QUEST_TURNED_IN" then
        local id, xp = ...
        record("T", id, xp)
        scheduleScan()
    elseif event == "QUEST_REMOVED" then
        local id = ...
        -- Removal also happens during turn-in. Do NOT label this "abandoned".
        record("R", id)
        scheduleScan()
    elseif event == "QUEST_LOG_UPDATE" then
        scheduleScan()
    elseif event == "PLAYER_LOGOUT" then
        exportQuests()
    end
end)
