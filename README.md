# Ricochet Grid

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
| `ricochet/config.py` | Velocidades, colores, rutas y constantes generales. |
| `ricochet/models.py` | Datos de tanques, balas, partículas y trazas. |
| `ricochet/geometry.py` | Cálculos de ángulos, segmentos y formas. |
| `ricochet/catalog.py` | Lectura y validación del catálogo de enemigos. |
| `ricochet/levels.py` | Cantidad, mezcla y orden de aparición por nivel. |
| `ricochet/world.py` | Grid, paredes, movimiento, A* y superficies de rebote. |
| `ricochet/combat.py` | Disparos, rebotes y colisiones de balas y tanques. |
| `ricochet/mines.py` | Colocación, activación, explosión y daño de minas. |
| `ricochet/audio.py` | Generación y reproducción del pitido de advertencia. |
| `ricochet/enemy_ai.py` | Movimiento, puntería y cálculo de rebotes enemigos. |
| `ricochet/renderer.py` | Carga de assets y dibujo de toda la interfaz. |
| `ricochet/game.py` | Niveles, eventos y coordinación de los sistemas. |
| `data/enemies.csv` | Cualidades editables de cada tipo de enemigo. |
| `data/map.txt` | Mapa: `0` es suelo, `1` pared sólida y `2` pared rompible. |
| `data/spawns.csv` | Puntos de aparición de enemigos. |
| `assets/*.svg` | Sprites editables por separado. |

## Datos Editables

Las velocidades y cadencias disponibles están en `ricochet/config.py`. Los enemigos usan sus nombres desde `data/enemies.csv`, que también contiene los límites de balas y minas.

Para modificar el escenario, edita `data/map.txt` sin cambiar la longitud de sus filas. Los sprites SVG se pueden abrir en un editor de texto o en cualquier editor vectorial.

## Minas

Pulsa `Espacio` durante la partida para colocar una mina. El jugador puede mantener dos minas activas. Se activan al cumplir ocho segundos, al detectar un tanque o al recibir una bala; después parpadean y pitan durante 1,5 segundos antes de explotar.

La explosión tiene tres tiles de diámetro, destruye tanques y rompe únicamente las paredes marcadas con `2` en `data/map.txt`.
