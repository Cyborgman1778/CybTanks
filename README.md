# CybTanks

Juego de tanques 2D hecho con Python y Pygame.

## Ejecutar

```powershell
py -m pip install pygame
py main.py
```

## Estructura

| Archivo | Contenido |
| --- | --- |
| `main.py` | Punto de entrada. Solo inicia el juego. |
| `cybtanks/config.py` | Velocidades, colores, rutas y constantes generales. |
| `cybtanks/models.py` | Datos de tanques, balas, partículas y trazas. |
| `cybtanks/geometry.py` | Cálculos de ángulos, segmentos y formas. |
| `cybtanks/catalog.py` | Lectura y validación del catálogo de enemigos. |
| `cybtanks/levels.py` | Cantidad, mezcla y orden de aparición por nivel. |
| `cybtanks/world.py` | Grid, paredes, movimiento, A* y superficies de rebote. |
| `cybtanks/combat.py` | Disparos, rebotes y colisiones de balas y tanques. |
| `cybtanks/mines.py` | Colocación, activación, explosión y daño de minas. |
| `cybtanks/audio.py` | Generación y reproducción del pitido de advertencia. |
| `cybtanks/enemy_ai.py` | Movimiento, puntería y cálculo de rebotes enemigos. |
| `cybtanks/renderer.py` | Carga de assets y dibujo de toda la interfaz. |
| `cybtanks/game.py` | Niveles, eventos y coordinación de los sistemas. |
| `data/enemies.csv` | Cualidades editables de cada tipo de enemigo. |
| `data/tank_attribute_options.csv` | Opciones válidas y explicación de cada cualidad. |
| `data/map.txt` | Mapa: `0` es suelo, `1` pared sólida y `2` pared rompible. |
| `data/spawns.csv` | Puntos de aparición de enemigos. |
| `assets/*.svg` | Sprites editables por separado. |

## Datos Editables

`data/enemies.csv` utiliza encabezados descriptivos en español. Las velocidades y cadencias disponibles están en `cybtanks/config.py`, y `data/tank_attribute_options.csv` resume sus valores, unidades y formatos permitidos.

Para modificar el escenario, edita `data/map.txt` sin cambiar la longitud de sus filas. Los sprites SVG se pueden abrir en un editor de texto o en cualquier editor vectorial.

## Minas

Pulsa `Espacio` durante la partida para colocar una mina. El jugador puede mantener dos minas activas. Una bala o un tanque la hacen explotar instantáneamente. Si nadie la toca, a los ocho segundos inicia un aviso de parpadeo y pitidos durante 1,5 segundos y después explota.

La explosión tiene tres tiles de diámetro, destruye tanques y rompe únicamente las paredes marcadas con `2` en `data/map.txt`.
Si otra mina se encuentra dentro del radio, ambas explotan en el mismo frame y la reacción puede continuar en cadena.

Los enemigos móviles consideran el radio de las minas como una zona peligrosa, buscan la salida segura más cercana y no vuelven a cruzarla mientras la mina siga activa. El gris claro conserva su propiedad de permanecer inmóvil.

## Enemigo Amarillo

El amarillo aparece a partir del nivel 5. Comparte disparo e inteligencia con el gris oscuro, se mueve a velocidad rápida y puede mantener hasta tres minas activas colocadas por su IA.

Los enemigos reservan destinos diferentes alrededor del jugador y penalizan las rutas que ya utilizan sus aliados. Si encuentran un tanque bloqueando el paso o dejan de avanzar, recalculan una ruta alternativa. También descartan disparos y colocaciones de minas que pondrían directamente a un aliado en peligro.

Las balas del jugador necesitan recorrer una distancia mínima antes de poder rebotar. Si se dispara directamente contra una pared estando pegado a ella, el proyectil se rompe en vez de rebotar. La distancia se configura con `PLAYER_MIN_RICOCHET_DISTANCE` en `cybtanks/config.py`.
