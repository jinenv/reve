# INTEGRATION GUIDE: Tiered Abilities + Advanced Combat Service

## 🎯 HOW THE COMPLETE SYSTEM WORKS

### 1. ABILITY RESOLUTION (Your Current System Enhanced)
```python
# AbilityService.resolve_esprit_abilities() follows this priority:

# TIERS 1-5: Universal Element-Based Abilities
if tier <= 5:
    # Get from "universal_element_abilities" section
    # All Inferno Esprits get same abilities, scaled by tier
    # Example: Tier 3 Inferno = "Fire Bolt" with ["burn"] effect
    
# TIERS 6+: Custom Esprit-Specific Abilities  
if tier >= 6:
    # Get from "custom_esprit_abilities" section
    # Each named Esprit gets unique custom abilities
    # Example: "Flameheart" = "Heart Burn" with ["burn", "vulnerability_mark", "power_siphon"]
```

### 2. COMBAT INTEGRATION
```python
# When player uses ability in combat:

# Step 1: Get ability from AbilityService
ability_data = await AbilityService.resolve_esprit_abilities("Flameheart", 6, "inferno")
# Returns: {"basic": {"name": "Heart Burn", "effects": ["burn", "vulnerability_mark", "power_siphon"]}}

# Step 2: Process in CombatService
damage = calculate_base_damage(attack, defense, ability_power)
for effect_name in ability_data.effects:
    await CombatService._apply_effect(effect_name, combat_state, "boss", damage, source_tier=6)
    
# Step 3: Advanced effects scale by tier
# Tier 6 Flameheart's "burn" = more powerful than Tier 1 basic burn
# Tier 6 gets "vulnerability_mark" + "power_siphon" that Tier 1-5 can't access
```

### 3. PROGRESSION EXAMPLES

## TIER 1 INFERNO ESPRIT:
```python
abilities = {
    "basic": {"name": "Ember Strike", "effects": []},           # No effects
    "ultimate": {"name": "Blazing Rage", "effects": ["burn"]}   # Basic burn only
}
# Effect scaling: burn = 5.5% damage per turn
```

## TIER 5 INFERNO ESPRIT:
```python  
abilities = {
    "basic": {"name": "Infernal Strike", "effects": ["burn", "vulnerability_mark"]},
    "ultimate": {"name": "Inferno Blast", "effects": ["burn", "elemental_weakness"]}
}
# Effect scaling: burn = 7.5% damage per turn, vulnerability = 20% per stack
```

## TIER 6 FLAMEHEART (CUSTOM):
```python
abilities = {
    "basic": {"name": "Heart Burn", "effects": ["burn", "vulnerability_mark", "power_siphon"]},
    "ultimate": {"name": "Soul Incinerate", "effects": ["burn", "berserker_rage", "elemental_weakness"]}
}
# Effect scaling: burn = 8% damage per turn, vulnerability = 21% per stack, siphon = 8% per turn
```

### 4. TEAM SYSTEM INTEGRATION
```python
# Player's team in combat:
team = {
    "leader": "Flameheart" (Tier 6),      # Full abilities + advanced effects
    "support1": "Thornguard" (Tier 7),   # Support skill: "Toxic Embrace" 
    "support2": "Stormcaller" (Tier 8)   # Support skill: "Lightning Speed"
}

# Combat actions available:
- "⚔️ Heart Burn" (Leader basic with 3 effects)
- "💥 Soul Incinerate" (Leader ultimate with 3 effects)  
- "🛡️ Toxic Embrace" (Support 1 skill)
- "⚡ Lightning Speed" (Support 2 skill)
```

### 5. EFFECT POWER SCALING
```python
# Same effect, different tiers = different power:

# TIER 1: power_siphon = 5.5% steal per turn
# TIER 6: power_siphon = 8% steal per turn  
# TIER 12: power_siphon = 11% steal per turn

# TIER 1: vulnerability_mark = 16% per stack, max 5 stacks
# TIER 6: vulnerability_mark = 21% per stack, max 6 stacks
# TIER 12: vulnerability_mark = 27% per stack, max 8 stacks
```

## 🔧 IMPLEMENTATION CHANGES NEEDED

### 1. UPDATE esprit_abilities.json
```bash
# Replace your current file with the new structure that includes:
- universal_element_abilities (Tiers 1-5)
- custom_esprit_abilities (Tiers 6+) 
- support_skills (for team combat)
- All abilities now have "effects" arrays with advanced combat effects
```

### 2. CombatService Integration
```python
# CombatService now:
✅ Gets actual tier from team leader  
✅ Scales all effects by tier automatically
✅ Processes multiple effects per ability
✅ Handles advanced effects with proper scaling
✅ Integrates with your existing team system
```

### 3. NO CHANGES NEEDED TO:
```python
❌ AbilityService resolution logic (works as-is)
❌ TeamService (works as-is)  
❌ Database models (works as-is)
❌ Existing quest/combat UI (works as-is)
```

## 🎮 COMBAT EXAMPLE

### Player Action:
```
Player uses Flameheart's "Soul Incinerate" (Tier 6 Ultimate)
```

### System Processing:
```python
# 1. Get ability data
ability = {"name": "Soul Incinerate", "power": 175, "effects": ["burn", "berserker_rage", "elemental_weakness"]}

# 2. Calculate damage  
base_damage = calculate_damage(player_attack, boss_defense, 175)  # 2,340 damage

# 3. Apply effects with Tier 6 scaling
await apply_effect("burn", target="boss", tier=6)           # 8% burn per turn
await apply_effect("berserker_rage", target="player", tier=6)  # +18% damage per turn, 4 turns
await apply_effect("elemental_weakness", target="boss", tier=6) # Next opposing attack = 2.6x damage

# 4. Combat result
- Boss takes 2,340 damage + burn DoT
- Player enters berserker rage (+18% damage stacking)  
- Boss vulnerable to water attacks (2.6x damage)
```

## 🚀 WHAT THIS GIVES YOU

### ✅ Perfect Tier Progression
- Tier 1-5: Universal abilities, progressively more effects
- Tier 6+: Custom unique abilities with advanced effect combinations
- Higher tiers = genuinely more powerful with same effect types

### ✅ Strategic Depth  
- Players must choose which advanced effects to prioritize
- Team composition matters (element matching, tier diversity)
- Combat becomes tactical with effect timing and resource management

### ✅ Easy to Expand
- Add new custom Esprits in "custom_esprit_abilities"
- Create new advanced effects in CombatService
- Scale difficulty by giving bosses advanced effects too

### ✅ Balanced Progression
- No single "best" effect - different situations need different strategies
- Higher tiers feel meaningfully more powerful
- Lower tiers still viable with good team composition

## 🎯 READY TO IMPLEMENT?

1. **Replace esprit_abilities.json** with the new structure
2. **CombatService is ready** - no additional changes needed
3. **Test with a Tier 6 custom Esprit** to see advanced effects in action
4. **Scale boss HP** to match new player power levels

**Your tiered ability system + advanced combat effects = strategic turn-based combat that scales perfectly from Tier 1 to Tier 12!**