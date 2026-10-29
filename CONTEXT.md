# CybTanks — Contexto Completo del Proyecto

## Visión General

Juego de tanques 2D top-down hecho con **Python 3.12** y **Pygame**. Un jugador contra oleadas de enemigos con IA táctica avanzada (Utility AI). Grid de 17×13 tiles, 8 mapas rotativos, 5 tipos de enemigo, minas, rebotes, escudos y sistema de vidas.

**Ejecutar:** `py main.py` (requiere `pygame`).

---

## Estructura de Archivos

```
main.py                    → Punto de entrada: Game().run()
cybtanks/
  config.py                → Constantes, rutas, velocidades, colores, carga de mapas
  models.py                → Dataclasses: Tank, Bullet, Mine, Particle, EnemyMemory, etc.
  geometry.py              → clamp, angle_difference, turn_towards, distancia punto-segmento/segmento-segmento, oriented_box
  catalog.py               → Carga y validación de data/enemies.csv
  ai_config.py             → Carga tipada de data/ai_profiles.json → AIProfile, GlobalAIConfig, AISettings
  ai_perception.py         → PerceptionSystem: visión (FOV+rango+LOS), oído (eventos sonoros+atenuación), LOD, detección progresiva
  ai_decision.py           → UtilityDecisionSystem: estados guard/investigate/search/attack/flank/cover/retreat/evade
  ai_squad.py              → SquadCoordinator: roles (assault/support/flanker), cupos de ataque, compartir contactos
  levels.py                → Cantidad, mezcla y orden de enemigos por nivel; selección de mapa
  world.py                 → Grid, paredes, colisiones AABB, A*, navigation_field (Dijkstra), LOS, superficies de rebote, cover_quality
  combat.py                → CombatSystem: disparos, trayectorias, rebotes, colisiones bala-tanque/bala-bala, friendly fire
  mines.py                 → MineSystem: colocación, activación, explosión, cadena, destrucción de muros rompibles
  audio.py                 → AudioSystem: generación procedural de 8 efectos de sonido (ondas + ruido)
  enemy_ai.py              → EnemyAISystem: 1750 líneas, orquesta percepción→decisión→navegación→movimiento→disparo
  renderer.py              → Renderer: carga SVG, dibuja tablero, tanques, balas, minas, partículas, explosiones, HUD
  input_manager.py         → Sistema de inputs unificado: KBM + Mando (hotplugging, deadzone, persistencia de apuntado, retícula adaptativa)
data/
  enemies.csv              → 5 tipos de enemigo con propiedades en español
  ai_profiles.json         → Perfiles IA: low, medium_low, medium, high, tactical + overrides por arquetipo
  map.txt ... map_8.txt    → Mapas 17×13 (0=suelo, 1=muro sólido, 2=muro rompible, 3=hoyo)
  spawns.csv               → 12 puntos de aparición de enemigos (col,row)
  tile_types.csv           → Propiedades de cada tipo de tile
  tank_attribute_options.csv → Referencia de opciones válidas para enemies.csv
assets/*.svg               → Sprites vectoriales editables
tests/
  test_tactical_ai.py      → Tests de IA táctica (47K)
  test_friendly_fire_ai.py → Tests de fuego amigo (27K)
  test_new_tank_features.py → Tests de features de tanques
  test_map_spawns.py       → Tests de spawns por mapa
GAMEPAD_SPEC.md            → Especificación de InputManager para soporte de mando (pendiente)
```

---

## Constantes Clave (config.py)

| Constante | Valor | Descripción |
|---|---|---|
| `TILE` | 60 px | Tamaño de celda |
| `ROWS × COLS` | 13 × 17 | Dimensiones del mapa |
| `TANK_HALF` | 17.0 | Media-caja del tanque |
| `BULLET_RADIUS` | 4.5 | Radio de colisión de bala |
| `MAX_BOUNCES` | 1 | Rebotes máx. por bala |
| `MAX_PLAYER_BULLETS` | 5 | Balas simultáneas del jugador |
| `MAX_PLAYER_MINES` | 2 | Minas simultáneas del jugador |
| `PLAYER_STARTING_LIVES` | 3 | Vidas iniciales |
| `PLAYER_SPEED` | 125 px/s | `MOVEMENT_SPEEDS["medium"]` |
| `PLAYER_BULLET_SPEED` | 230 px/s | `BULLET_SPEEDS["slow"]` |
| `MINE_EXPLOSION_RADIUS` | 90 px | `TILE * 1.5` |
| `MINE_AUTO_TRIGGER_TIME` | 8.0 s | Auto-detonación |
| `MINE_WARNING_DURATION` | 1.5 s | Parpadeo pre-explosión |
| `HUD_HEIGHT` | 86 px | Barra superior |
| `WINDOW_SIZE` | (1020, 866) | Ventana completa |

**Velocidades de movimiento:** `stopped=0, slow=58, medium=125, fast=180` px/s  
**Velocidades de bala:** `slow=230, fast=516` px/s  
**Cadencias de disparo:** `slow=0.75, medium=0.55, tactical=0.50, normal=0.38, fast=0.16` s  
**Tiempos de pensar disparo:** `slow=0.90, medium=0.50, fast=0.15` s

---

## Modelo de Datos (models.py)

### Tank (dataclass)
Campos principales: `tank_id`, `team` ("player"/"enemy"), `kind` (player/light_gray/dark_gray/yellow/dark_green/pink), `spawn_cell`, `position` (Vec2), `body_angle`, `turret_angle`, `speed`, `color`, `bullet_speed_class`, `bullet_speed`, `max_bullets`, `max_bounces`, `max_mines`, `fire_rate`, `shot_think_speed`, `intelligence`, `ricochet_accuracy`, `ricochet_success_rate`, `self_safe`, `shield_hits`, `alive`, `velocity`, `cooldown`, `fire_timer`, `shot_think_timer`, `path` (list[GridCell]), `goal`, `aim_angle`, `shot_ready`, `escaping_mines`, `stuck_timer`, `route_seed`, `recent_cells`, `ai` (EnemyMemory).

### EnemyMemory (dataclass)
Estado cognitivo: `state` (guard/investigate/search/attack/flank/cover/retreat/evade), `role` (assault/support/flanker), `awareness` (0→1), `target_visible`, `has_line_of_sight`, `last_known_position`, `memory_remaining`, `hearing_remaining`, `reaction_remaining`, `sensor_timer`, `decision_timer`, `navigation_target`, `threat`, `lod_factor`, `dodge_timer/cooldown/direction`, `aim_predictive`, `aim_requires_hit`, `aim_expected_bounces`.

### Bullet: `position`, `velocity`, `team`, `owner_id`, `speed_class`, `max_bounces`, `bounces`, `age`, `distance_travelled`, `travel_budget`.

### Mine: `position`, `owner_id`, `team`, `age`, `triggered`, `warning_elapsed`, `owner_has_left`.

### Otros: `Particle`, `ExplosionEffect`, `TrackMark`, `ShotTrace` (target_hit, self_hit, ally_hit).

---

## Tipos de Enemigo (enemies.csv)

| Tipo | Movimiento | Bala | Rebotes | Minas | Cadencia | Inteligencia | Aparición |
|---|---|---|---|---|---|---|---|
| **light_gray** | stopped | slow | 1 | 0 | slow | high | Nivel 1+ |
| **dark_gray** | slow (58) | slow | 1 | 0 | slow | medium_low | Nivel 1+ |
| **yellow** | fast (180) | slow | 1 | 3 | slow | medium_low | Nivel 5+ |
| **dark_green** | slow (58) | fast (516) | 0 | 0 | medium | medium | Nivel 8+ |
| **pink** | medium (125) | slow | 1 | 0 | tactical (0.50) | tactical | Nivel 10+ |

- **Escudos:** Dark gray desde nivel 12 (1 escudo, 2 desde nivel 21).
- Rebote: light_gray y pink = `accurate` (100%); dark_gray y yellow = `imperfect` (58%); dark_green = `imperfect` (78%, sin rebotes).
- Todos tienen `evita_autodestruccion=true`.

---

## Sistema de Juego (game.py)

### Clase Game
- **Estado:** `playing`, `life_lost`, `level_clear`, `game_over`.
- **Bucle principal:** 60 FPS, `dt` limitado a 1/30. Orden: `handle_events` → `update` → `render`.
- **Update:** Actualizar cooldowns → `update_player` → `enemy_ai.update` → `record_tank_tracks` → `combat.update` → `mine_system.update` → `evaluate_state`.
- **make_tank():** Crea Tank con stats del catálogo según tipo. Inicializa IA para enemigos.
- **Niveles:** Infinitos, rotan 8 mapas. Cada 5 niveles +1 vida. Al perder una vida: limpiar balas/minas, restaurar muros, respawnear enemigos vivos en spawn original, jugador en celda segura más cercana. Al perder todas: reiniciar nivel con 3 vidas.
- **Controles:** WASD/flechas (mover), ratón (apuntar torreta), LMB (disparar), Espacio (mina), R (reintentar), Enter/Espacio/clic (siguiente nivel), Escape (salir).

---

## Mundo y Navegación (world.py)

### Clase World
- **Grid:** `tiles[row][col]` — 0=suelo, 1=muro sólido, 2=rompible, 3=hoyo.
- **Colisiones:** `blocks_tank(cell)` → tile ≠ 0; `blocks_bullet(cell)` → tile ∈ {1,2}. Hoyo (3) bloquea tanques pero NO balas.
- **move_tank():** Movimiento por ejes independientes con resolución de empuje en cadena. Si el último tanque choca con pared → nadie se mueve. Acepta `movement_allowed` callback para filtrar movimientos (usado para friendly fire).
- **find_path():** A* con 4-vecinos, celdas bloqueadas, penalizaciones por celda. Heurística Manhattan.
- **navigation_field():** Dijkstra completo desde un punto, genera `costs` y `came_from` para reconstruir cualquier ruta. Acepta `transition_allowed` para validar transiciones (usado en escape de minas).
- **clear_segment():** Comprueba si un segmento está libre de muros (para LOS y disparos).
- **sound_attenuation():** Atenuación de sonido a través de paredes (producto de factores por pared).
- **cover_quality():** Evalúa calidad de cobertura de una celda respecto a una amenaza (0–1, con bonus de asomo).
- **bounce_surfaces:** Lista precalculada de superficies de rebote (eje, coordenada, min, max).
- **break_walls():** Destruye muros rompibles (tipo 2→0) en un radio. Recalcula bounce_surfaces.
- **revision:** Incrementa en cada cambio de tiles para invalidar caches.

### Funciones auxiliares
- `grid_cell(Vec2) → (col, row)`: Convierte posición a celda.
- `cell_center((col, row)) → Vec2`: Centro de una celda en píxeles.

---

## Sistema de Combate (combat.py)

### CombatSystem
- **shoot(tank):** Crea bala en muzzle seguro (no dentro de pared), aplica cooldown, genera burst y sonido.
- **can_shoot(tank):** `alive + cooldown≤0 + shot_think_timer≤0 + state=="playing" + balas_activas < max`.
- **Movimiento de balas:** Subdividido en pasos de `SHOT_TRACE_STEP=3.0` px. Por paso: mover X, comprobar pared → rebotar/destruir. Mover Y, comprobar. Tras mover: colisiones bala-bala, bala-mina, bala-tanque.
- **Rebotes:** Máx 1 por defecto. Bala del jugador: si `distance_travelled < PLAYER_MIN_RICOCHET_DISTANCE (24)` y no ha rebotado → se destruye (no rebota contra pared pegada).
- **Escudo:** `hit_tank()` → si `shield_hits > 0`: consume escudo, flash. Si no: `destroy_tank()`.
- **trace_shot():** Simula trayectoria completa para IA. Devuelve `ShotTrace(target_hit, self_hit, ally_hit, target_bounces, target_distance)`.
- **Friendly fire:** `prepare_friendly_fire_paths()` precalcula trayectorias de balas aliadas. `movement_safe_from_friendly_fire()` valida que un movimiento no cruce una bala aliada. `ally_route_touches_shot()` verifica rutas de aliados contra posición de disparo.
- **projectile_path_segments():** Calcula trayectoria futura de un proyectil incluyendo rebotes, colisiones con tanques estacionarios, minas y otros proyectiles. Cachea resultados.

---

## Sistema de Minas (mines.py)

### MineSystem
- **place(tank):** Coloca si `alive + max_mines + estado playing + separación_mín=30 px`.
- **Ciclo de vida:** `age` crece cada frame. A los 8s → trigger (parpadeo + beeps 0.18s). A los 1.5s de warning → explode.
- **Explosión:** Radio `MINE_EXPLOSION_RADIUS=90px`. Destruye balas, hace cadena con otras minas, destruye tanques (ignora escudos), rompe muros tipo 2.
- **owner_has_left:** Mina no afecta a su dueño hasta que se aleje `MINE_TRIGGER_RADIUS=25px`.
- **Trigger por contacto:** Cualquier tanque a ≤25px de una mina (excepto el dueño antes de alejarse).

---

## IA Enemiga — Arquitectura Completa (enemy_ai.py, 1750 líneas)

### Pipeline por frame (EnemyAISystem.update)
1. Incrementar `_now`, comenzar frame de percepción y squad.
2. Precalcular friendly fire paths.
3. Asignar presupuestos por frame (path/shot/predictive).
4. Round-robin con cursor rotativo entre enemigos vivos.
5. Por enemigo: percepción → squad share → decisión → `update_enemy()`.

### update_enemy() — por cada enemigo cada frame
1. **Timers:** Decrementar fire/mine/plan/aim/dodge/avoid.
2. **Dodge:** Si no hay peligro de mina → `dodge_incoming_fire()`. Proyecta trayectorias de balas hostiles (incluyendo rebotes), calcula esquivas laterales continuas con commitment para no oscilar.
3. **Stuck detection:** Progreso neto < TILE*0.25 durante `net_stuck_timeout` → abandonar ruta.
4. **Navegación (si speed>0):**
   - Si mina cercana → `plan_mine_escape()` (Dijkstra con `transition_allowed` que no acerque a minas).
   - Si no → `plan_path()` usando `navigation_field()` + scoring táctico por candidato.
5. **Movimiento:** Seguir path, pop waypoints al llegar. Si bloqueado → intentar desvío lateral. Manejar celdas compartidas (crowded cell coordination). Aplicar `steer_around_friendly_fire()` y `_steer_away_from_mines()`.
6. **Minas IA (yellow):** Si `max_mines > 0`, timer cumplido, aliados seguros → colocar.
7. **Apuntado y disparo:**
   - Sin target visible → scan oscillation.
   - Con target → calcular solución de disparo (`choose_shot()`).
   - Pre-validar con `trace_shot()` justo antes de disparar.
   - Si predicción activada: cancelar si el jugador cambió trayectoria.

### plan_path() — Navegación táctica
1. Calcular `mine_blocked_cells()` y `route_penalties()`.
2. Ejecutar `navigation_field()` (Dijkstra) desde posición actual.
3. Generar candidatos con scoring por estado:
   - **attack:** Distancia ideal al target + firing lane + cobertura.
   - **flank:** Alineación lateral + distancia preferida.
   - **cover:** Maximizar calidad de cobertura (≥0.6).
   - **retreat:** Maximizar distancia + cobertura.
   - **investigate/search:** Ir al contacto oído/recordado.
4. Desempate con: reservas de goals, variant hash (ruta única por enemigo), penalización de celdas recientes.
5. Reconstruir path desde navigation field.

### route_penalties() — Diversificación de rutas
- Penalizar celdas ocupadas por aliados.
- Penalizar primeras 10 celdas del path de aliados.
- Penalizar goals reservados.
- Penalizar 10 últimas celdas visitadas.
- Penalizar celda avoid.
- Ruido pseudoaleatorio por `route_seed ^ route_variant`.

### choose_shot() — Selección de disparo
Prioridad: (1) Predictive direct → (2) Predictive ricochet → (3) Static direct → (4) Static ricochet → (5) Fallback al ángulo directo.
- **Predictive:** Calcula intercepción lineal, itera convergencia de origen/tiempo, prueba offsets perpendiculares. Para rebotes: espejo sobre superficies, itera convergencia, valida con trace_shot.
- **Ricochet accuracy:** `accurate` siempre acierta, `imperfect` tiene probabilidad (`ricochet_success_rate`). Fallo: aplica error angular aleatorio y revalida.
- **Seguridad:** Todo disparo se verifica contra self_hit y ally_hit.

### dodge_incoming_fire() — Esquiva de proyectiles
- Proyecta trayectorias de balas hostiles (incluyendo rebotes) en horizonte configurable.
- Detecta amenaza inminente (bullet más cercana en tiempo).
- Evalúa candidatos de esquiva: dirección comprometida anterior, perpendiculares al disparo, alejarse del punto más cercano.
- Descarta candidatos que: choquen con pared, colisionen con aliados, entren en radio de mina, crucen bala aliada.
- Commitment: mantiene dirección elegida durante `dodge_commit_time` para no oscilar.
- Tanques con `speed=0` (light_gray) nunca esquivan.

---

## IA — Percepción (ai_perception.py)

### PerceptionSystem
- **Visión:** FOV configurable, rango en tiles, LOS real (clear_segment). Detección progresiva: `awareness` 0→1 con factor de distancia y bonus por movimiento. Al confirmar: `reaction_time` antes de poder disparar.
- **Oído:** Eventos sonoros con radio, atenuación por paredes. Tipos: shot_slow, shot_fast, explosion, mine_place, mine_trigger, tank_destroyed. Motor del jugador como sonido continuo.
- **Memoria:** `memory_remaining` decae si target no visible. `last_known_position` se mantiene durante memoria.
- **LOD:** `lod_factor` 0→1 según distancia. Intervalos de sensor y decisión se interpolan entre near y far.
- **Omnisciente:** Si `omniscient_player_tracking=true` (activo por defecto): posición exacta del jugador cada frame, pero LOS sigue necesaria para disparar.

---

## IA — Decisión (ai_decision.py)

### UtilityDecisionSystem
- **Estados:** guard, investigate, search, attack, flank, cover, retreat, evade.
- **Evaluación utility:** Pondera aggression, cover_preference, flank_preference, retreat_threshold. Modifica por: rol (assault/support/flanker), exposición, threat level, pérdida de escudo, hysteresis, ruido pseudoaleatorio.
- **Threat level:** Proyectiles entrantes (con trayectoria completa), presión por cercanía, exposición LOS, pérdida de escudo.
- **Transiciones:** Timer por LOD factor. Si estado o target_cell cambia → limpiar path, replannear.

---

## IA — Squad (ai_squad.py)

### SquadCoordinator
- **Roles:** assault, support, flanker. Asigna `preferred_role` del profile. Si ningún móvil es assault → el más rápido lo es. Inmóviles siempre support.
- **Attack slots:** Máximo `max_attackers` simultáneos. Reserva con duración `attack_slot_duration`. Liberar al fallar disparo.
- **Share contact:** Observador con target visible comparte `last_known_position` a aliados cercanos (dentro de `communication_range_tiles`). Solo si no tienen ya target visible. Aplica `alert_awareness`, resetea `decision_timer`.

---

## IA — Configuración (ai_config.py + ai_profiles.json)

### AIProfile (65 campos)
Percepción: vision_range/fov/detection/memory/hearing. Decisión: aggression/cover_preference/flank_preference/retreat_threshold/unpredictability. Movimiento: preferred/min/max_distance, navigation_search_radius, navigation_interval, stuck_timeouts. Combate: aim_interval/tolerance, ricochet candidates/error, dodge parameters. Predicción: horizon/step/iterations, prediction_min_target_speed. Squad: preferred_role. Scan: speed/arc.

### GlobalAIConfig (40+ campos)
Presupuestos: max_path/shot/predictive_shot_plans_per_frame, max_attackers. LOD: near/far_lod_distance_tiles. Omnisciente: omniscient_player_tracking. Rutas: route_occupied/ally_path/reserved_goal/recent/avoid/noise penalties. Minas: danger_penalty, initial_delay/stagger. Sonido: sound_ranges_tiles, attenuation. Combate: friendly_fire_horizon, direct_aim_offsets_px, dodge_candidate_angles. Entidades: max_enemy_bullets/mines/bounces.

### Perfiles por inteligencia
- **low:** (Sin usar aún) Percepción mínima.
- **medium_low:** dark_gray, yellow. Visión/oído limitados, sin predicción.
- **medium:** dark_green. Mejor puntería, FOV más amplio.
- **high:** light_gray. Casi tactical pero con tiempos peores. Predicción activa.
- **tactical:** pink. Máxima capacidad, predicción avanzada, mantiene distancia 3-5 tiles.

### Overrides por arquetipo (en ai_profiles.json)
Permiten ajustar campos específicos de un profile para un kind concreto (ej. pink tiene overrides de distancia, flank_preference, etc.).

---

## Renderizado (renderer.py)

### Renderer
- Carga SVGs de assets/ al inicio.
- **Board background:** Surface estática con tiles de suelo/muro/hoyo. Se reconstruye al destruir muros.
- **Orden de dibujo:** HUD → board_background → tracks → aim_guide → mines → wrecks → enemies → player → bullets → explosions → particles → reticle → end_screen.
- **Tanques:** Shadow + body SVG rotado + turret SVG rotado + shield circle + health bar.
- **Balas rápidas:** Llama SVG animada detrás del proyectil.
- **Tracks:** Huellas de oruga con fade de 4s, alpha calculado.
- **Explosiones:** Onda expansiva con easing cúbico, core luminoso, anillo exterior.
- **HUD:** Título "CYB TANKS", controles, nivel, hostiles restantes, balas, minas, vidas.
- **End screen:** Overlay semitransparente con mensaje según estado.
- **Retícula:** Crosshair animado en posición del ratón.

---

## Audio (audio.py)

### AudioSystem
Genera 8 efectos proceduralmente (sin archivos de audio):
- `slow_shot`: Tono descendente 235→165 Hz + crack de ruido, 0.13s.
- `fast_shot`: Chirp 1350 Hz con sweep cuadrático, 0.085s.
- `bullet_bounce`: Metálico 1050 Hz con armónico ×2.37, 0.095s.
- `bullet_disintegrate`: Fragmentos + ruido, 0.15s.
- `mine_beep`: Sinusoide 1050 Hz, 0.055s.
- `mine_place`: Clunk 175 Hz + latch 720 Hz, 0.12s.
- `explosion`: Rumble 64 Hz + ruido filtrado + crack, 0.48s.
- `tank_destroyed`: Impacto 125 Hz + metal 610+1080 Hz + debris, 0.34s.

---

## Niveles (levels.py)

- `enemy_layout(level)`: Genera tipos y spawns. Cuenta crece `2 + (level-1)//2`, máx 12. Mezcla basada en nivel con shuffle determinista (`Random(level * 7919)`).
- `map_layout(level)`: `MAP_LAYOUTS[(level-1) % 8]`.
- `shielded_dark_gray_count(level)`: 0 si <12, 1 si 12-20, 2 si ≥21.
- Mapas pueden tener spawns personalizados (`#player_spawn=`, `#enemy_spawn=`).

---

## Mapas (data/map*.txt)

- 8 mapas de 17×13 tiles.
- Formato: líneas de dígitos 0-3. Comentarios con `#`.
- Metadatos opcionales: `#player_spawn=col,row`, `#enemy_spawn=kind,col,row`.
- Tile 3 (hoyo): bloquea tanques/spawns/A*, NO bloquea balas/visión/rebotes.

---

## Tests

| Archivo | Líneas | Cobertura |
|---|---|---|
| `test_tactical_ai.py` | 1300+ | IA táctica completa, estados, navegación, predicción, esquiva |
| `test_friendly_fire_ai.py` | 700+ | Prevención de fuego amigo, rutas, disparos, minas |
| `test_new_tank_features.py` | 200+ | Shield, shot_think_timer, track marks |
| `test_map_spawns.py` | 100+ | Validación de spawns por mapa |

Ejecutar: `py -m pytest tests/`

---

## Pendiente

- **InputManager (GAMEPAD_SPEC.md):** Módulo `input_manager.py` para soporte unificado teclado+ratón / mando gamepad. Spec completa en el archivo. No implementado aún.

---

## Convenciones del Código

- **Idioma:** Código en inglés, documentación/datos/UI en español.
- **Tipos:** `from __future__ import annotations` en todos los módulos. Type hints extensivos. `Vec2 = pygame.Vector2`, `GridCell = tuple[int, int]`.
- **Dataclasses:** Inmutables con `frozen=True, slots=True` para configuración. Mutables para entidades de juego.
- **Caches:** Por id/signature, invalidados manualmente. `lru_cache` para ai_settings.
- **Validación:** Exhaustiva en carga de datos. Campos desconocidos, rangos, coherencia.
- **Coordenadas:** `(col, row)` para grid, `Vec2(x, y)` para mundo. Ángulos en radianes. `atan2(y, x)`.
- **Colisiones tanque:** AABB con half=17. **Colisiones bala:** Círculo con radius=4.5.
- **Dependencias circulares:** Resueltas con `TYPE_CHECKING` + strings en annotations.

