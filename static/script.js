// FUNCIONES DE AUTENTICACIÓN

function mostrarLogin() {
    document.getElementById('loginForm').classList.add('active');
    document.getElementById('registroForm').classList.remove('active');
    document.querySelectorAll('.tab-btn')[0].classList.add('active');
    document.querySelectorAll('.tab-btn')[1].classList.remove('active');
}

function mostrarRegistro() {
    document.getElementById('registroForm').classList.add('active');
    document.getElementById('loginForm').classList.remove('active');
    document.querySelectorAll('.tab-btn')[1].classList.add('active');
    document.querySelectorAll('.tab-btn')[0].classList.remove('active');
}

function mostrarMensaje(elementoId, mensaje, tipo) {
    const elemento = document.getElementById(elementoId);
    elemento.textContent = mensaje;
    elemento.className = 'message show ' + tipo;
    setTimeout(() => {
        elemento.classList.remove('show');
    }, 4000);
}

// LOGIN
async function login(event) {
    event.preventDefault();
    
    const telefono = document.getElementById('phone-login').value;
    const password = document.getElementById('password-login').value;
    
    try {
        const response = await fetch('/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                telefono: telefono,
                password: password
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            mostrarMensaje('login-message', data.mensaje, 'success');
            setTimeout(() => {
                window.location.href = data.ir_a;
            }, 1500);
        } else {
            mostrarMensaje('login-message', data.error, 'error');
        }
    } catch (error) {
        mostrarMensaje('login-message', 'Error en la conexión', 'error');
    }
}

// REGISTRO
async function registro(event) {
    event.preventDefault();
    
    const nombre = document.getElementById('nombre').value;
    const telefono = document.getElementById('phone-registro').value;
    const password = document.getElementById('password-registro').value;
    const banco = document.getElementById('banco').value;
    
    try {
        const response = await fetch('/registro', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                nombre: nombre,
                telefono: telefono,
                password: password,
                banco: banco
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            mostrarMensaje('registro-message', data.mensaje, 'success');
            setTimeout(() => {
                window.location.href = data.ir_a;
            }, 1500);
        } else {
            mostrarMensaje('registro-message', data.error, 'error');
        }
    } catch (error) {
        mostrarMensaje('registro-message', 'Error en la conexión', 'error');
    }
}

// ACTUALIZAR PERFIL
async function actualizarPerfil(event) {
    event.preventDefault();
    
    const nombre = document.getElementById('edit-nombre').value;
    const banco = document.getElementById('edit-banco').value;
    
    try {
        const response = await fetch('/actualizar_perfil', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                nombre: nombre,
                banco: banco
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            mostrarMensaje('perfil-message', data.mensaje, 'success');
            document.getElementById('nombre').textContent = nombre;
            document.getElementById('banco').textContent = banco;
        } else {
            mostrarMensaje('perfil-message', data.error, 'error');
        }
    } catch (error) {
        mostrarMensaje('perfil-message', 'Error en la conexión', 'error');
    }
}

// COMPRAR PRODUCTO
async function comprarProducto(productoId) {
    try {
        const response = await fetch('/comprar_producto', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                producto_id: productoId
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            mostrarMensaje('producto-message', data.mensaje, 'success');
            setTimeout(() => {
                location.reload();
            }, 1500);
        } else {
            mostrarMensaje('producto-message', data.error, 'error');
        }
    } catch (error) {
        mostrarMensaje('producto-message', 'Error en la conexión', 'error');
    }
}

// LOGOUT
function logout() {
    window.location.href = '/';
}
