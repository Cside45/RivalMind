local _, RM = ...

-- No minimap button, automatic popup, combat alert, or persistent HUD by default.
local panel = CreateFrame("Frame", "RivalMindSessionPanel", UIParent, "BackdropTemplate")
panel:SetSize(255, 126)
panel:SetFrameStrata("DIALOG")
panel:SetClampedToScreen(true)
panel:SetMovable(true)
panel:EnableMouse(true)
panel:RegisterForDrag("LeftButton")
panel:SetBackdrop({
    bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
    edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
    tile = true, tileSize = 16, edgeSize = 16,
    insets = { left = 4, right = 4, top = 4, bottom = 4 },
})
panel:Hide()

local title = panel:CreateFontString(nil, "OVERLAY", "GameFontNormal")
title:SetPoint("TOPLEFT", 14, -14)
title:SetText("RivalMind | Session")

local close = CreateFrame("Button", nil, panel, "UIPanelCloseButton")
close:SetPoint("TOPRIGHT", -4, -4)
close:SetScript("OnClick", function() RM.SetPanelVisible(false) end)

local details = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
details:SetPoint("TOPLEFT", 14, -42)
details:SetPoint("BOTTOMRIGHT", -14, 12)
details:SetJustifyH("LEFT")
details:SetJustifyV("TOP")

local function restorePosition()
    local settings = RM.GetSettings()
    panel:ClearAllPoints()
    if settings then
        local allowed = { CENTER = true, TOPLEFT = true, TOPRIGHT = true, BOTTOMLEFT = true, BOTTOMRIGHT = true }
        local point = allowed[settings.point] and settings.point or "CENTER"
        panel:SetPoint(point, UIParent, point, tonumber(settings.x) or 0, tonumber(settings.y) or 0)
    else
        panel:SetPoint("CENTER")
    end
end

panel:SetScript("OnDragStart", function(self) self:StartMoving() end)
panel:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    local settings = RM.GetSettings()
    if not settings then return end
    local point, _, _, x, y = self:GetPoint(1)
    settings.point = point or "CENTER"
    settings.x, settings.y = math.floor(x or 0), math.floor(y or 0)
end)

function RM.RefreshPanel()
    if not panel:IsShown() then return end
    local session = RM.GetCurrentSession()
    if not session then
        details:SetText("Waiting for character data...")
        return
    end
    local seconds = RM.GetSessionSeconds()
    local rate = math.floor((session.xpEarned or 0) * 3600 / seconds)
    details:SetText(string.format("Level: %d  |  Time: %dm\nXP gained: %d  (%d/hr)\nDeaths: %d  |  Sessions: %d\nZone: %s",
        session.endLevel or 0, math.floor(seconds / 60), session.xpEarned or 0, rate,
        session.deaths or 0, RM.GetSessionCount(), session.zone or "Unknown"))
end

function RM.SetPanelVisible(visible)
    local settings = RM.GetSettings()
    if settings then settings.showPanel = not not visible end
    if visible then
        restorePosition()
        panel:Show()
        RM.RefreshPanel()
    else
        panel:Hide()
    end
end

function RM.TogglePanel()
    RM.SetPanelVisible(not panel:IsShown())
end

-- Five-second UI refresh only while the window is visible.
local elapsed = 0
panel:SetScript("OnUpdate", function(_, dt)
    elapsed = elapsed + dt
    if elapsed > 5 then elapsed = 0; RM.RefreshPanel() end
end)

local startup = CreateFrame("Frame")
startup:RegisterEvent("PLAYER_ENTERING_WORLD")
startup:SetScript("OnEvent", function(self)
    self:UnregisterAllEvents()
    local settings = RM.GetSettings()
    if settings and settings.showPanel then RM.SetPanelVisible(true) end
end)
