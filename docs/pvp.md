# Two-Stage PvP Battle System

## Overview
PvP battles use ALL 6 elements across two sequential 3v3 stages, ensuring complete roster utilization while keeping individual battles manageable.

## Battle Format
- **Stage 1**: 3v3 battle using first element group
- **Stage 2**: 3v3 battle using remaining element group  
- **Victory**: Win both stages OR win one stage with higher total damage

## Element Assignment Options
### Option A: Player Choice
- Player selects 3 elements for Stage 1
- Remaining 3 auto-assigned to Stage 2
- Strategy: Front-load power vs. save for comeback

### Option B: Fixed Groups
- **Primary**: Inferno, Verdant, Abyssal
- **Advanced**: Tempest, Umbral, Radiant
- Consistent strategy, no choice paralysis

### Option C: Element Wheel
- Groups based on element counter-relationships
- Maximum tactical depth

## Strategic Benefits
- ✅ Uses complete 6-element roster
- ✅ Can't ignore "weak" elements  
- ✅ Rewards balanced progression
- ✅ Creates comeback potential
- ✅ Makes every T12 Esprit valuable for PvP
- ✅ Maintains individual excellence focus (vs PvE total army power)

## Implementation Notes
- Each stage uses simplified abilities (no complex state tracking)
- Battle resolution per stage: damage calculation + simple effects
- Element bonuses/penalties apply within each stage
- Compatible with existing tier/awakening/leadership systems