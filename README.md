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
| `cybtanks/audio.py` | Generación y reproducción de los efectos de sonido. |
| `cybtanks/enemy_ai.py` | Movimiento, puntería y cálculo de rebotes enemigos. |
| `cybtanks/renderer.py` | Carga de assets y dibujo de toda la interfaz. |
| `cybtanks/game.py` | Niveles, eventos y coordinación de los sistemas. |
| `data/enemies.csv` | Cualidades editables de cada tipo de enemigo. |
| `data/tank_attribute_options.csv` | Opciones válidas y explicación de cada cualidad. |
| `data/map*.txt` | Mapas: `0` suelo, `1` pared sólida, `2` pared rompible y `3` hoyo. |
| `data/tile_types.csv` | Colisiones y propiedades de cada tipo de tile. |
| `data/spawns.csv` | Puntos de aparición de enemigos. |
| `assets/*.svg` | Sprites editables por separado. |

## Datos Editables

`data/enemies.csv` utiliza encabezados descriptivos en español. Las velocidades y cadencias disponibles están en `cybtanks/config.py`, y `data/tank_attribute_options.csv` resume sus valores, unidades y formatos permitidos.

Los niveles rotan entre ocho escenarios. Para modificarlos, edita `data/map.txt` y `data/map_2.txt` a `data/map_8.txt` sin cambiar sus dimensiones. Los sprites SVG se pueden abrir en un editor de texto o en cualquier editor vectorial.

El tile `3` representa un hoyo. Bloquea tanques, empujes, respawns y rutas A*, pero las balas, la visión y los cálculos de rebote pasan por encima sin colisionar.

## Efectos Audiovisuales

Los disparos lentos y rápidos tienen sonidos distintos, al igual que el rebote y la desintegración de sus proyectiles. Colocar una mina, producir una explosión y destruir un tanque también generan efectos diferenciados. Las explosiones muestran una onda sobre toda el área de daño, y los tanques móviles dejan huellas de oruga que se desvanecen durante cuatro segundos.

## Minas

Pulsa `Espacio` durante la partida para colocar una mina. El jugador puede mantener dos minas activas. Una bala o un tanque la hacen explotar instantáneamente. Si nadie la toca, a los ocho segundos inicia un aviso de parpadeo y pitidos durante 1,5 segundos y después explota.

La explosión tiene tres tiles de diámetro, destruye tanques y proyectiles dentro de su radio, y rompe únicamente las paredes marcadas con `2` en el mapa activo.
Si otra mina se encuentra dentro del radio, ambas explotan en el mismo frame y la reacción puede continuar en cadena.

Los enemigos móviles consideran el radio de las minas como una zona peligrosa, buscan la salida segura más cercana y no vuelven a cruzarla mientras la mina siga activa. El gris claro conserva su propiedad de permanecer inmóvil.

## Enemigo Amarillo

El amarillo aparece a partir del nivel 5. Comparte disparo e inteligencia con el gris oscuro, se mueve a velocidad rápida y puede mantener hasta tres minas activas colocadas por su IA.

Los enemigos reservan destinos diferentes alrededor del jugador y penalizan las rutas que ya utilizan sus aliados. Un tanque ocupado reduce la prioridad de una ruta, pero no la bloquea: si es el mejor camino disponible, avanzan por él y pueden empujarse. Todos los enemigos móviles enlazan destinos para mantenerse en movimiento; solo los tipos con velocidad `stopped` permanecen quietos por decisión propia. También descartan disparos y colocaciones de minas que pondrían directamente a un aliado en peligro. La comprobación cubre los tramos continuos de sus próximas rutas, y los tanques desvían su movimiento para no entrar en la trayectoria de una bala aliada.

## Enemigo Verde Oscuro

El verde oscuro aparece a partir del nivel 8. Se mueve como el gris oscuro, utiliza proyectiles de `516 px/s`, empieza a disparar antes, usa cadencia media y espera a alinear mejor la torreta antes de disparar. Sus balas rápidas muestran una llama animada detrás del proyectil.

Cada tanque móvil recibe una semilla de ruta distinta al comenzar y recuerda las últimas celdas recorridas. Esto cambia los desempates de A*, evita bucles y hace que una misma posición inicial pueda producir caminos diferentes entre intentos.

## Enemigo Rosado

El rosado aparece a partir del nivel 10. Se mueve a velocidad media, dispara proyectiles lentos con un rebote, no coloca minas y tiene una cadencia exacta de `0.50 s`. Su inteligencia táctica mantiene entre tres y cinco tiles de distancia, prioriza posiciones con línea de tiro y recalcula antes su puntería.

## Escudos

Desde el nivel 12, algunos tanques gris oscuro aparecen con un escudo azul. El primer impacto de bala consume el escudo y destruye el proyectil, pero el tanque sobrevive. Las explosiones de mina atraviesan esta protección. El escudo consumido no se recupera al reaparecer el jugador.

## Vidas

El jugador comienza la partida con tres vidas y conserva las restantes al avanzar de nivel. Al superar los niveles 5, 10, 15 y sucesivos recibe una vida adicional acumulable.

Al perder una vida se limpian balas y minas, el mapa recupera todos sus muros y los enemigos supervivientes regresan a sus puntos de aparición. Los enemigos que ya fueron destruidos permanecen destruidos. Después el jugador reaparece en la celda segura más cercana.

Cuando se agotan todas las vidas se reinicia el nivel completo y regresan todos sus enemigos con tres vidas iniciales.

## Empuje Entre Tanques

El movimiento vuelve a responder inmediatamente a los controles, sin inercia ni fricción. Cuando un tanque avanza contra otro intenta empujarlo, y el empuje puede propagarse por una cadena de varios tanques. Si el último queda bloqueado por una pared, ninguno de los tanques de la cadena se desplaza.

## Pensamiento De Disparo

`tiempo_pensar_disparo` en `data/enemies.csv` es distinto de `cadencia_disparo`. Cuando desaparece una bala propia, el tanque debe esperar este nuevo tiempo antes de poder disparar otra: `slow=0.90`, `medium=0.50` y `fast=0.15` segundos. El jugador usa rápido; el amarillo y el rosado usan medio; los demás tipos usan lento.

Las balas del jugador necesitan recorrer una distancia mínima antes de poder rebotar. Si se dispara directamente contra una pared estando pegado a ella, el proyectil se rompe en vez de rebotar. La distancia se configura con `PLAYER_MIN_RICOCHET_DISTANCE` en `cybtanks/config.py`.
