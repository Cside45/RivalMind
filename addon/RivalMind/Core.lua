-- RivalMind 0.2.0-alpha | World of Warcraft: Forever (Interface 16001)
-- Privacy: no network calls, no addon messages, no chat collection.
-- This build intentionally does NOT attempt to read restricted combat logs.
local _, RM = ...
RM = RM or {}
local MAX_SESSIONS = 100
local current

local function numberOrZero(value)
    if type(value) ~= "number" then return 0 end
    if value ~= value or value < 0 then return 0 end
    return math.floor(value)
end

local function getCharacterXP()
    local ok, level, xp, maximum = pcall(function()
        return UnitLevel("player"), UnitXP("player"), UnitXPMax("player")
    end)
    if not ok or type(level) ~= "number" or type(xp) ~= "number" or type(maximum) ~= "number" then
        return nil
    end
    return numberOrZero(level), numberOrZero(xp), numberOrZero(maximum)
end

local function getZone()
    local ok, value = pcall(GetZoneText)
    if ok and type(value) == "string" then return value end
    return ""
end

local function percentEncode(value)
    return (tostring(value or ""):gsub("([^%w%-%._])", function(c)
        return string.format("%%%02X", string.byte(c))
    end))
end

local function initialize()
    if type(RivalMindDB) ~= "table" or RivalMindDB.schema ~= 1 then
        RivalMindDB = {
            schema = 1,
            nextID = 0,
            sessions = {},
            settings = { showPanel = false, point = "CENTER", x = 0, y = 0 },
        }
    end
    if type(RivalMindDB.sessions) ~= "table" then RivalMindDB.sessions = {} end
    if type(RivalMindDB.settings) ~= "table" then
        RivalMindDB.settings = { showPanel = false, point = "CENTER", x = 0, y = 0 }
    end
    RivalMindDB.nextID = numberOrZero(RivalMindDB.nextID)
    while #RivalMindDB.sessions > MAX_SESSIONS do
        table.remove(RivalMindDB.sessions, 1)
    end
end

-- A per-character local ID allocated by the account SavedVariables file.
-- WoW stores RivalMindCharDB separately per character. No name, realm or GUID
-- is exported or needed for partitioning the local analytics.
function RM.GetCharacterID()
    if type(RivalMindDB) ~= "table" then return 0 end
    if type(RivalMindCharDB) ~= "table" then RivalMindCharDB = {} end
    local id = numberOrZero(RivalMindCharDB.id)
    if id == 0 or id > 100000000 then
        RivalMindDB.nextCharacterID = numberOrZero(RivalMindDB.nextCharacterID) + 1
        id = RivalMindDB.nextCharacterID
        RivalMindCharDB.id = id
    end
    if numberOrZero(RivalMindDB.nextCharacterID) < id then
        RivalMindDB.nextCharacterID = id
    end
    return id
end

function RM.GetSettings()
    return RivalMindDB and RivalMindDB.settings
end

function RM.GetCurrentSession()
    return current
end

function RM.GetSessionCount()
    if not RivalMindDB then return 0 end
    return #RivalMindDB.sessions
end

function RM.GetSessionSeconds()
    if not current then return 0 end
    return math.max(1, time() - current.started)
end

function RM.PrintStatus()
    local session = current
    if not session then
        print("|cff80c5ffRivalMind|r: No session yet.")
        return
    end
    local seconds = RM.GetSessionSeconds()
    local xpRate = math.floor(session.xpEarned * 3600 / seconds)
    print(string.format("|cff80c5ffRivalMind|r: %d XP gained, %d XP/hr, %d deaths, %d stored sessions.",
        session.xpEarned, xpRate, session.deaths, RM.GetSessionCount()))
end

local function exportSessions()
    -- A strict, simple, ASCII-only interchange format. The companion parses this
    -- string as DATA, never executes Lua or evaluates a SavedVariables file.
    local rows = { "RM2" }
    for _, session in ipairs(RivalMindDB.sessions) do
        rows[#rows + 1] = table.concat({
            numberOrZero(session.id),
            numberOrZero(session.started),
            numberOrZero((session.last or session.started) - session.started),
            numberOrZero(session.xpEarned),
            numberOrZero(session.deaths),
            numberOrZero(session.startLevel),
            numberOrZero(session.endLevel),
            percentEncode(session.zone),
            numberOrZero(session.characterID),
        }, ",")
    end
    RivalMindDB.export = table.concat(rows, ";")
end

local function startSession()
    if current then return end
    initialize()
    local level, xp, maximum = getCharacterXP()
    local now = time()
    RivalMindDB.nextID = RivalMindDB.nextID + 1
    current = {
        id = RivalMindDB.nextID,
        characterID = RM.GetCharacterID(),
        started = now,
        last = now,
        xpEarned = 0,
        deaths = 0,
        startLevel = level or 0,
        endLevel = level or 0,
        lastXP = xp,
        lastXPMax = maximum,
        lastLevel = level,
        zone = getZone(),
    }
    local sessions = RivalMindDB.sessions
    sessions[#sessions + 1] = current
    while #sessions > MAX_SESSIONS do table.remove(sessions, 1) end
    exportSessions()
    if RM.RefreshPanel then RM.RefreshPanel() end
end

local function recordXP()
    if not current then return end
    local level, xp, maximum = getCharacterXP()
    if not level then return end
    local previousLevel, previousXP, previousMax = current.lastLevel, current.lastXP, current.lastXPMax
    if previousLevel and previousXP and previousMax then
        local gained = 0
        if level == previousLevel and xp >= previousXP then
            gained = xp - previousXP
        elseif level == previousLevel + 1 and previousMax > 0 then
            gained = math.max(0, previousMax - previousXP) + xp
        end
        -- Guard against unusual API changes and bogus event values.
        if gained >= 0 and gained <= 1000000 then
            current.xpEarned = current.xpEarned + gained
        end
    end
    current.lastXP, current.lastXPMax, current.lastLevel = xp, maximum, level
    current.endLevel = level
    current.last = time()
    if RM.RefreshPanel then RM.RefreshPanel() end
end

local handler = {
    PLAYER_ENTERING_WORLD = startSession,
    PLAYER_XP_UPDATE = recordXP,
    PLAYER_DEAD = function()
        if current then
            current.deaths = current.deaths + 1
            current.last = time()
            if RM.RefreshPanel then RM.RefreshPanel() end
        end
    end,
    ZONE_CHANGED_NEW_AREA = function()
        if current then current.zone = getZone(); current.last = time() end
    end,
    PLAYER_LOGOUT = function()
        if current then current.last = time(); current.zone = getZone() end
        if RivalMindDB then exportSessions() end
    end,
}

local events = CreateFrame("Frame")
for eventName in pairs(handler) do
    -- Forever throws for unknown/unsupported events. Fail gracefully.
    pcall(events.RegisterEvent, events, eventName)
end

events:SetScript("OnEvent", function(_, eventName)
    local fn = handler[eventName]
    if fn then fn() end
end)

SLASH_RIVALMIND1 = "/rivalmind"
SLASH_RIVALMIND2 = "/rm"
SlashCmdList.RIVALMIND = function(input)
    input = (input or ""):lower():match("^%s*(.-)%s*$")
    if input == "status" then
        RM.PrintStatus()
    elseif input == "quests" then
        if RM.PrintQuestStatus then RM.PrintQuestStatus() end
    elseif input == "telemetry" then
        if RM.PrintTelemetryStatus then RM.PrintTelemetryStatus() end
    elseif input == "show" then
        if RM.SetPanelVisible then RM.SetPanelVisible(true) end
    elseif input == "hide" then
        if RM.SetPanelVisible then RM.SetPanelVisible(false) end
    elseif input == "help" then
        print("|cff80c5ffRivalMind|r: /rm [show | hide | status | quests | telemetry | help]")
    else
        if RM.TogglePanel then RM.TogglePanel() end
    end
end
