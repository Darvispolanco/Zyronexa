# Zyronexa - Aplicación de Autofinanciamiento

Zyronexa es una aplicación web de autofinanciamiento construida con Flask que permite a los usuarios invertir en diferentes productos y generar ganancias diarias automáticas.

## Características

- 🔐 Sistema de autenticación seguro con contraseñas hasheadas
- 💰 8 planes de inversión disponibles (Básico a Diamante)
- 📈 Generación automática de ganancias diarias
- 👤 Gestión de perfil de usuario
- 📊 Panel de control con estadísticas
- 🔑 Panel de administrador para el propietario

## Requisitos

- Python 3.7+
- Flask 2.3.3
- Werkzeug 2.3.7

## Instalación

1. Clona el repositorio:
```bash
git clone https://github.com/Darvispolanco/Zyronexa.git
cd Zyronexa
```

2. Crea un entorno virtual:
```bash
python -m venv venv
```

3. Activa el entorno virtual:
   - En Windows:
   ```bash
   venv\Scripts\activate
   ```
   - En macOS/Linux:
   ```bash
   source venv/bin/activate
   ```

4. Instala las dependencias:
```bash
pip install -r requirements.txt
```

## Ejecución

1. Ejecuta la aplicación:
```bash
python Zironexa.py
```

2. Abre tu navegador y ve a:
```
http://localhost:5000
```

## Planes de Inversión

| Plan | Precio | Ganancia Diaria |
|------|--------|----------------|
| Básico | ₡500 | ₡20 |
| Estándar | ₡1,000 | ₡40 |
| Plus | ₡1,500 | ₡60 |
| Pro | ₡2,000 | ₡80 |
| Premium | ₡3,000 | ₡120 |
| Elite | ₡5,000 | ₡200 |
| Platinum | ₡10,000 | ₡400 |
| Diamante | ₡20,000 | ₡800 |

## Acceso de Propietario

- Teléfono: `84907210`
- Contraseña: `admin123`

## Estructura del Proyecto

```
Zyronexa/
├── Zironexa.py              # Aplicación principal
├── requirements.txt         # Dependencias de Python
├── zironexa.db             # Base de datos SQLite
├── templates/              # Plantillas HTML
│   ├── index.html          # Página de inicio
│   ├── usuario.html        # Panel de usuario
│   └── propietario.html    # Panel del propietario
└── static/                 # Archivos estáticos
    ├── style.css           # Estilos CSS
    └── script.js           # Scripts JavaScript
```

## Base de Datos

La aplicación utiliza SQLite con tres tablas principales:

### Usuarios
- ID, nombre, teléfono, contraseña, banco
- Información de saldo y ganancias
- Datos del producto activo

### Historial
- Registro de todas las transacciones
- Tipo de transacción, monto y fecha

### Productos
- ID, nombre, precio, ganancia diaria

## Notas de Seguridad

⚠️ **IMPORTANTE**: Esta es una aplicación de demostración. Para producción:
- Cambia la clave secreta de Flask
- Configura variables de entorno para datos sensibles
- Implementa verificación de dos factores
- Usa HTTPS
- Implementa limitación de tasa (rate limiting)
- Agrega validación más robusta

## Licencia

Este proyecto es de código abierto.

## Autor

[Darvis Polanco](https://github.com/Darvispolanco)
