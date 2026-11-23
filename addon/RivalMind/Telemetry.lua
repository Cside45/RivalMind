-- RivalMind v0.4-alpha: opt-in-free LOCAL observations only; no networking.
-- Event-driven, bounded storage. No raw combat events or player identifiers.
local _, RM = ...
local MAX_EVENTS = 600
local records
local nextID = 0
local equipment = {}
local lastGold
local lastZoneKey
local bagCounts
local bagPending = false
local bagContext = "unattributed"
local merchantOpen = false
local lootOpen = false

local function integer(v, allowNegative)
    local ok, result = pcall(function()
        if type(v) ~= "number" or v ~= v then return nil end
        if math.abs(v) > 500000000000 then return nil end
        if v < 0 and not allowNegative then return nil end
        return math.floor(v)
    end)
    return ok and result or nil
end

local function safeText(v, maxLen)
    local ok, result = pcall(function()
        if type(v) ~= "string" then return "" end
        if issecretvalue and issecretvalue(v) then return "" end
        return v:sub(1, maxLen)
    end)
    return ok and result or ""
end

local function encode(v)
    return (safeText(v, 80):gsub("([^%w%-%._])", function(ch)
        return string.format("%%%02X", string.byte(ch))
    end))
end

local function store()
    if type(RivalMindDB) ~= "table" then return nil end
    if type(RivalMindDB.telemetryEvents) ~= "table" then
        RivalMindDB.telemetryEvents = {}
    end
    records = RivalMindDB.telemetryEvents
    nextID = integer(RivalMindDB.nextTelemetryID) or 0
    while #records > MAX_EVENTS do table.remove(records, 1) end
    return records
end

local function record(kind, a, b, c)
    if not records and not store() then return end
    nextID = nextID + 1
    RivalMindDB.nextTelemetryID = nextID
    records[#records + 1] = {
        id = nextID, stamp = integer(time()) or 0,
        kind = kind, a = a, b = b, c = c,
        characterID = RM.GetCharacterID and RM.GetCharacterID() or 0
    }
    while #records > MAX_EVENTS do table.remove(records, 1) end
end

local function characterSnapshot()
    local ok, token, level = pcall(function()
        local _, classFile = UnitClass("player")
        return classFile, UnitLevel("player")
    end)
    if not ok then return end
    local class = safeText(token, 24)
    level = integer(level)
    if class ~= "" and level then
        local key = class .. ":" .. tostring(level)
        if RM.lastCharacterKey ~= key then
            RM.lastCharacterKey = key
            record("C", class, level, "")
        end
    end
end

local function equipmentSnapshot(slot)
    local first, last = 1, 19
    local specified = integer(slot)
    if specified and specified >= 1 and specified <= 19 then
        first, last = specified, specified
    end
    for i = first, last do
        local ok, value = pcall(GetInventoryItemID, "player", i)
        if ok then
            -- nil means empty slot; a restricted/unreadable value means unknown.
            local id = integer(value)
            if value == nil then id = 0 end
            if id and equipment[i] ~= id then
                -- S = first observed equipment state after load; D = later
                -- genuine slot change. E from older v0.4 is ambiguous.
                local kind = equipment[i] == nil and "S" or "D"
                equipment[i] = id
                record(kind, i, id, "")
            end
        end
    end
end

local function moneySnapshot()
    local ok, value = pcall(GetMoney)
    if not ok then return end
    local amount = integer(value)
    if not amount then return end
    if lastGold == nil then
        record("G", amount, "", "baseline") -- initial balance, NOT gold earned
    elseif lastGold ~= amount then
        record("G", amount, amount - lastGold,
            merchantOpen and "merchant_window" or "unattributed")
    end
    lastGold = amount
end

local function zoneSnapshot()
    local ok, zone, subzone = pcall(function()
        return GetZoneText(), GetSubZoneText()
    end)
    if not ok then return end
    zone, subzone = safeText(zone, 80), safeText(subzone, 80)
    if zone == "" then return end
    local key = zone .. "\1" .. subzone
    if key ~= lastZoneKey then
        lastZoneKey = key
        record("Z", zone, subzone, "")
    end
end

local function readBags()
    if type(C_Container) ~= "table"
        or type(C_Container.GetContainerNumSlots) ~= "function"
        or type(C_Container.GetContainerItemInfo) ~= "function" then
        return nil
    end
    local quantities = {}
    for bag = 0, 4 do
        local ok, slots = pcall(C_Container.GetContainerNumSlots, bag)
        if not ok or type(slots) ~= "number" or slots < 0 or slots > 100 then
            return nil -- unknown state: never manufacture deltas
        end
        for slot = 1, slots do
            local valid, info = pcall(C_Container.GetContainerItemInfo, bag, slot)
            if not valid then return nil end
            if info then
                local fieldsOK, id, quantity = pcall(function()
                    return integer(info.itemID), integer(info.stackCount)
                end)
                if not fieldsOK then return nil end
                if id and id > 0 and quantity and quantity > 0 then
                    quantities[id] = (quantities[id] or 0) + quantity
                end
            end
        end
    end
    return quantities
end

local function bagSnapshot()
    bagPending = false
    local now = readBags()
    if not now then return end
    local context = bagContext
    bagContext = "unattributed"
    if bagCounts then
        local changes = {}
        for id, count in pairs(now) do
            local delta = count - (bagCounts[id] or 0)
            if delta ~= 0 then changes[id] = delta end
        end
        for id, count in pairs(bagCounts) do
            if not now[id] then changes[id] = -count end
        end
        for id, delta in pairs(changes) do
            record("B", id, delta, context)
        end
    end
    bagCounts = now
end

local function requestBagSnapshot()
    if merchantOpen then bagContext = "merchant_window"
    elseif lootOpen and bagContext ~= "merchant_window" then bagContext = "loot_window" end
    if bagPending then return end
    bagPending = true
    if C_Timer and type(C_Timer.After) == "function" then
        C_Timer.After(0.8, bagSnapshot)
    else
        bagSnapshot()
    end
end

local function exportTelemetry()
    if not records and not store() then return end
    local rows = { "RT2" }
    for _, entry in ipairs(records) do
        local kind = entry.kind
        local a, b, c = entry.a, entry.b, entry.c
        if kind == "C" or kind == "Z" then
            a = encode(a)
        else
            a = tostring(a or "")
        end
        if kind == "Z" then b = encode(b) else b = tostring(b or "") end
        rows[#rows + 1] = table.concat({
            tostring(integer(entry.id) or 0),
            tostring(integer(entry.stamp) or 0),
            kind,
            a,
            b,
            tostring(c or ""),
            tostring(integer(entry.characterID) or 0),
        }, ",")
    end
    RivalMindDB.telemetryExport = table.concat(rows, ";")
end

function RM.PrintTelemetryStatus()
    if not records and not store() then return end
    print(string.format("|cff80c5ffRivalMind|r: %d local telemetry events (max %d). Gold: %s copper. No uploads.",
        #records, MAX_EVENTS, lastGold and tostring(lastGold) or "unknown"))
end

local events = CreateFrame("Frame")
for _, event in ipairs({
    "PLAYER_ENTERING_WORLD", "PLAYER_LOGOUT", "PLAYER_LEVEL_UP",
    "PLAYER_EQUIPMENT_CHANGED", "PLAYER_MONEY", "BAG_UPDATE_DELAYED",
    "ZONE_CHANGED", "ZONE_CHANGED_NEW_AREA", "ZONE_CHANGED_INDOORS",
    "MERCHANT_SHOW", "MERCHANT_CLOSED", "LOOT_OPENED", "LOOT_CLOSED",
}) do
    pcall(events.RegisterEvent, events, event)
end

events:SetScript("OnEvent", function(_, event, ...)
    if event == "PLAYER_ENTERING_WORLD" then
        store()
        characterSnapshot()
        equipmentSnapshot()
        moneySnapshot()
        zoneSnapshot()
        requestBagSnapshot()
    elseif event == "MERCHANT_SHOW" then
        merchantOpen = true
    elseif event == "MERCHANT_CLOSED" then
        merchantOpen = false
    elseif event == "LOOT_OPENED" then
        lootOpen = true
    elseif event == "LOOT_CLOSED" then
        lootOpen = false
    elseif event == "PLAYER_LEVEL_UP" then
        characterSnapshot()
    elseif event == "PLAYER_EQUIPMENT_CHANGED" then
        equipmentSnapshot(...)
    elseif event == "PLAYER_MONEY" then
        moneySnapshot()
    elseif event == "BAG_UPDATE_DELAYED" then
        requestBagSnapshot()
    elseif event == "ZONE_CHANGED" or event == "ZONE_CHANGED_NEW_AREA"
        or event == "ZONE_CHANGED_INDOORS" then
        zoneSnapshot()
    elseif event == "PLAYER_LOGOUT" then
        exportTelemetry()
    end
end)
