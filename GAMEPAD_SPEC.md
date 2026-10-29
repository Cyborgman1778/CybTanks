# Especificación Técnica: Sistema de Inputs Unificado (Mando + Teclado/Ratón) en Pygame

## 📌 Contexto del Proyecto
* **Motor:** Python (`pygame` o `pygame-ce`).
* **Tipo de Juego:** 2D Top-Down / Grid con movimiento continuo.
* **Objetivo:** Refactorizar el sistema de control para soportar dos esquemas de entrada intercambiables en tiempo real sin reiniciar ni reconfigurar:
  1. **Teclado + Ratón (KBM):** Movimiento continuo con `WASD`, apuntado con posición del cursor en pantalla, disparo con clic izquierdo y habilidad especial con tecla configurable (`Espacio` / `Shift` / `E`).
  2. **Mando / Gamepad (Twin-Stick):**
     * **Stick Izquierdo (LS):** Movimiento continuo analógico.
     * **Stick Derecho (RS):** Dirección de apuntado vectorial continuo.
     * **Gatillo Derecho (RT) o RB:** Disparo.
     * **Gatillo Izquierdo (LT) o Botón Frontal (A/X):** Habilidad especial.

---

## 🎯 Instrucciones de Implementación

Implementa un módulo desacoplado `input_manager.py` y adapta el bucle principal (`main.py`) y la clase `Player`.

---

### 1. Estructura de Datos Unificada (`InputState`)

Crea un `dataclass` que represente la intención del jugador en el frame actual, agnóstico del dispositivo:

```python
from dataclasses import dataclass
import pygame

@dataclass
class InputState:
    move_vector: pygame.Vector2       # Vector normalizado (-1.0 a 1.0) para movimiento continuo
    aim_vector: pygame.Vector2        # Vector unitario de dirección de apuntado
    aim_world_pos: pygame.Vector2     # Coordenada absoluta de apuntado (cursor en KBM / proyección en mando)
    shoot_triggered: bool             # True si se disparó en este frame (click / RT down)
    shoot_held: bool                  # True si se mantiene presionado el botón de disparo
    special_triggered: bool           # True si se activó la habilidad especial en este frame
    active_mode: str                  # 'KBM' | 'GAMEPAD'
```

---

### 2. Módulo `InputManager`

Crea la clase `InputManager` para centralizar la captura de eventos y el cálculo del estado:

#### A. Inicialización y Reconexión en Caliente (*Hotplugging*)
* Inicializar el subsistema con `pygame.joystick.init()`.
* Manejar eventos `pygame.JOYDEVICEADDED` y `pygame.JOYDEVICEREMOVED` para conectar y desconectar mandos en tiempo de ejecución de forma segura.

#### B. Filtrado de Zona Muerta (*Deadzone*)
Aplica una zona muerta radial a los sticks analógicos para prevenir deriva (*drift*):

```python
def apply_deadzone(axis_x: float, axis_y: float, threshold: float = 0.18) -> pygame.Vector2:
    vec = pygame.Vector2(axis_x, axis_y)
    if vec.length() < threshold:
        return pygame.Vector2(0, 0)
    return vec.normalize()
```

#### C. Mapeo de Ejes y Botones
* **Stick Izquierdo (Movimiento):** Ejes 0 (X) y 1 (Y).
* **Stick Derecho (Apuntado):** Ejes 2/3 (X) y 3/4 (Y).
  * **Importante:** Si el stick derecho vuelve a la zona muerta ($|v| = 0$), no resetear a `(0, 0)`; conservar el último vector de apuntado válido para que el personaje no pierda la orientación al soltar la palanca.
* **Disparo:** Gatillo `RT` (eje analógico con valor $> 0.5$) o botón `RB` / `R1`.
* **Habilidad Especial:** Gatillo `LT` o botón `A` / `Cross`.

#### D. Detección Dinámica de Dispositivo Activo
* Si se recibe `KEYDOWN` (WASD/Especial) o `MOUSEMOTION`/`MOUSEBUTTONDOWN` $ightarrow$ `active_mode = 'KBM'`.
* Si se recibe `JOYAXISMOTION` (superando la deadzone) o `JOYBUTTONDOWN` $ightarrow$ `active_mode = 'GAMEPAD'`.

---

### 3. Renderizado de Retícula (*Crosshair*)

Implementa el método `draw_crosshair(surface, player_screen_pos)`:
* **En modo KBM:** Dibuja la retícula en la coordenada real del cursor (`pygame.mouse.get_pos()`).
* **En modo GAMEPAD:** Proyecta la retícula a una distancia fija $D$ (ej. 120 px) desde el centro del jugador en la dirección de `aim_vector`:
  $$\text{CrosshairPos} = \text{PlayerPos} + (\text{aim\_vector} \times D)$$

---

### 4. Integración en `Player`

La clase `Player` no debe leer `pygame.key` ni `pygame.mouse`. Debe procesar exclusivamente el `InputState`:

```python
class Player:
    def update(self, dt: float, input_state: InputState):
        # 1. Movimiento continuo
        if input_state.move_vector.length_squared() > 0:
            self.velocity = input_state.move_vector * self.speed
            self.position += self.velocity * dt
        else:
            self.velocity = pygame.Vector2(0, 0)

        # 2. Rotación / Orientación
        if input_state.aim_vector.length_squared() > 0:
            self.facing_angle = input_state.aim_vector.angle_to(pygame.Vector2(1, 0))

        # 3. Disparo
        if input_state.shoot_triggered and self.can_shoot():
            self.shoot(input_state.aim_vector)

        # 4. Habilidad Especial
        if input_state.special_triggered and self.can_use_special():
            self.use_special_ability()
```

---

### 5. Criterios de Aceptación y Calidad
1. **Tolerancia a fallos:** Si no hay mando conectado, el juego inicia y corre en modo Teclado + Ratón sin excepciones.
2. **Movimiento fluido:** El stick izquierdo permite movimiento omnidireccional analógico suave.
3. **Persistencia de mira:** Soltar el stick derecho mantiene la dirección hacia donde se apuntó por última vez.
4. **Desacoplamiento estricto:** `player.py` no debe contener referencias a `pygame.joystick`.
