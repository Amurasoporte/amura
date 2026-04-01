from flask import Flask, render_template, request, jsonify, session, redirect, abort
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import uuid
import re
from functools import wraps
from sqlalchemy import func

app = Flask(__name__)

# ========== CONFIGURACIÓN ==========
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'amura-secret-key-2024-cambiar-en-produccion')
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Configurar base de datos según entorno
if os.environ.get('DATABASE_URL'):
    # En producción (Render) - usar PostgreSQL
    database_url = os.environ.get('DATABASE_URL')
    # Corregir el formato si es necesario (postgres:// -> postgresql://)
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # En desarrollo local - usar SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///amura.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configuración de archivos estáticos
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static/uploads/kyc', exist_ok=True)

db = SQLAlchemy(app)

# Socket.IO - modo threading para compatibilidad con Render
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ============================
# DECORADORES DE AUTORIZACIÓN
# ============================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'tipo' not in session:
            return redirect('/')
        return f(*args, **kwargs)
    return decorated_function

def superadmin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('tipo') != 'supervisor':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def agencia_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('tipo') != 'agencia':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def modelo_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('tipo') != 'modelo':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# ============================
# MODELOS DE BASE DE DATOS
# ============================
class Agencia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    comision = db.Column(db.Integer, default=50)
    pais = db.Column(db.String(100), default='No especificado')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    perfiles = db.relationship('Perfil', backref='agencia', lazy=True, cascade='all, delete-orphan')

class Perfil(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    edad = db.Column(db.Integer, default=20)
    ubicacion = db.Column(db.String(100), default='No especificada')
    estado_hoy = db.Column(db.String(200), default='✨ Disponible para chatear ✨')
    biografia = db.Column(db.Text, default='Hola! Encantada de conocerte 💕')
    intereses = db.Column(db.String(300), default='Música, Viajes, Café')
    signo = db.Column(db.String(50))
    idiomas = db.Column(db.String(100), default='Español')
    foto_principal = db.Column(db.String(200), default='default_user.png')
    foto_portada = db.Column(db.String(200), default='default_cover.png')
    creditos_generados = db.Column(db.Integer, default=0)
    is_online = db.Column(db.Boolean, default=False)
    ultima_conexion = db.Column(db.DateTime, default=datetime.utcnow)
    ultima_ip = db.Column(db.String(50))
    agencia_id = db.Column(db.Integer, db.ForeignKey('agencia.id'))
    verificado = db.Column(db.Boolean, default=False)
    documento_identidad = db.Column(db.String(200), nullable=True)
    pais = db.Column(db.String(100))
    estado = db.Column(db.String(100))
    genero = db.Column(db.String(20))
    orientacion_sexual = db.Column(db.String(20))
    estado_civil = db.Column(db.String(50))
    trabajo = db.Column(db.String(100))
    educacion = db.Column(db.String(100))
    habitos = db.Column(db.String(200))
    estatura = db.Column(db.String(20))
    color_piel = db.Column(db.String(50))
    buscando_desc = db.Column(db.Text, default='Personas interesantes, respetuosas y con ganas de conectar.')
    edad_min = db.Column(db.Integer, default=18)
    edad_max = db.Column(db.Integer, default=95)
    fotos = db.relationship('Foto', backref='perfil', lazy=True, cascade='all, delete-orphan')

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre_real = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    edad = db.Column(db.Integer, default=25)
    pais = db.Column(db.String(100), default='Colombia')
    estado = db.Column(db.String(100))
    estado_hoy = db.Column(db.String(200), default='Buscando nuevas conexiones ✨')
    biografia = db.Column(db.Text, default='Me encanta conocer gente nueva y compartir momentos especiales')
    intereses = db.Column(db.String(300), default='Música, Cine, Deporte')
    foto_perfil = db.Column(db.String(200), default='default_user.png')
    creditos = db.Column(db.Integer, default=50)
    genero = db.Column(db.String(20), default='Hombre')
    orientacion_sexual = db.Column(db.String(20), default='Heterosexual')
    busco = db.Column(db.String(20), default='Mujeres')
    edad_min = db.Column(db.Integer, default=18)
    edad_max = db.Column(db.Integer, default=95)
    intencion = db.Column(db.String(50), default='No lo sé aún')
    estado_civil = db.Column(db.String(50))
    trabajo = db.Column(db.String(100))
    educacion = db.Column(db.String(100))
    habitos = db.Column(db.String(200))
    estatura = db.Column(db.String(20))
    color_piel = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    fotos_subidas = db.relationship('ClienteFoto', backref='cliente', lazy=True, cascade='all, delete-orphan')
    favoritos_dados = db.relationship('Favorito', backref='cliente', lazy=True, cascade='all, delete-orphan')

class Mensaje(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contenido = db.Column(db.Text, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    tipo_emisor = db.Column(db.String(20))
    emisor_cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'))
    emisor_perfil_id = db.Column(db.Integer, db.ForeignKey('perfil.id'))
    receptor_cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'))
    receptor_perfil_id = db.Column(db.Integer, db.ForeignKey('perfil.id'))
    creditos_generados = db.Column(db.Integer, default=1)
    bloqueado_por_scam = db.Column(db.Boolean, default=False)
    motivo_bloqueo = db.Column(db.String(200), nullable=True)

class Favorito(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'))
    perfil_id = db.Column(db.Integer, db.ForeignKey('perfil.id'))
    es_match = db.Column(db.Boolean, default=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    perfil = db.relationship('Perfil', backref='favoritos_recibidos')

class Foto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    perfil_id = db.Column(db.Integer, db.ForeignKey('perfil.id'))
    ruta = db.Column(db.String(200), nullable=False)
    es_privada = db.Column(db.Boolean, default=False)
    costo = db.Column(db.Integer, default=10)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)

class FotoComprada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'))
    foto_id = db.Column(db.Integer, db.ForeignKey('foto.id'))
    fecha_compra = db.Column(db.DateTime, default=datetime.utcnow)

class ClienteFoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'))
    ruta = db.Column(db.String(200), nullable=False)
    es_principal = db.Column(db.Boolean, default=False)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)

class Rate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    accion = db.Column(db.String(50), unique=True)
    creditos_costo = db.Column(db.Integer, default=1)
    creditos_ganancia_modelo = db.Column(db.Integer, default=1)
    valor_usd = db.Column(db.Float, default=0.10)
    activo = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class LogConexion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    perfil_id = db.Column(db.Integer, db.ForeignKey('perfil.id'))
    tipo = db.Column(db.String(20))
    ip = db.Column(db.String(50))
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    perfil = db.relationship('Perfil', backref='logs_conexion')

def registrar_log_conexion(perfil_id, tipo, ip):
    log = LogConexion(perfil_id=perfil_id, tipo=tipo, ip=ip)
    db.session.add(log)
    db.session.commit()

def detectar_scam(contenido):
    patrones = [
        r'\b\d{7,15}\b', 
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        r'(whatsapp|wa\.me|instagram|ig\.com|facebook|fb\.com|twitter|x\.com|t\.me|telegram|tiktok|linkedin|snapchat)',
        r'https?://[^\s]+', 
        r'www\.[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    ]
    contenido_lower = contenido.lower()
    for patron in patrones:
        if re.search(patron, contenido_lower):
            return True, "No está permitido compartir números de teléfono, correos, redes sociales o enlaces externos."
    return False, None

def obtener_rate(accion='chat'):
    rate = Rate.query.filter_by(accion=accion).first()
    if not rate:
        rate = Rate(accion=accion, creditos_costo=1, creditos_ganancia_modelo=1, valor_usd=0.10)
        db.session.add(rate)
        db.session.commit()
    return rate

def init_rates():
    acciones = ['chat', 'mail', 'video']
    for acc in acciones:
        if not Rate.query.filter_by(accion=acc).first():
            db.session.add(Rate(accion=acc, creditos_costo=1, creditos_ganancia_modelo=1, valor_usd=0.10))
    db.session.commit()

def init_db():
    with app.app_context():
        db.create_all()
        init_rates()
        
        # Crear superadmin si no existe
        if not Agencia.query.filter_by(correo='master@amura.com').first():
            admin = Agencia(
                nombre='Master Admin',
                correo='master@amura.com',
                password_hash=generate_password_hash('master123'),
                comision=0,
                pais='Admin'
            )
            db.session.add(admin)
            db.session.commit()
            print("Superadmin creado correctamente")

# ============================
# RUTAS DE AUTENTICACIÓN
# ============================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/registro')
def registro():
    return render_template('registro.html')

@app.route('/api/completar_registro', methods=['POST'])
def completar_registro():
    data = request.get_json()
    if Cliente.query.filter_by(correo=data.get('email')).first():
        return jsonify({'success': False, 'msg': 'El correo ya está registrado'}), 400
    
    nuevo_cliente = Cliente(
        nombre_real=data.get('nombre'),
        correo=data.get('email'),
        password_hash=generate_password_hash(data.get('password')),
        edad=int(data.get('edad', 18)),
        pais=data.get('pais'),
        estado=data.get('estado'),
        genero=data.get('genero'),
        orientacion_sexual=data.get('orientacion_sexual'),
        busco=data.get('busco'),
        edad_min=int(data.get('edad_min', 18)),
        edad_max=int(data.get('edad_max', 95)),
        intencion=data.get('intencion'),
        estado_civil=data.get('estado_civil'),
        trabajo=data.get('trabajo'),
        educacion=data.get('educacion'),
        habitos=data.get('habitos'),
        estatura=data.get('estatura'),
        color_piel=data.get('color_piel'),
        intereses=data.get('intereses'),
        creditos=50
    )
    db.session.add(nuevo_cliente)
    db.session.commit()
    
    session['user_id'] = nuevo_cliente.id
    session['tipo'] = 'cliente'
    session.permanent = True
    return jsonify({'success': True, 'redirect': '/app'})

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if email == 'master@amura.com' and password == 'master123':
        session['tipo'] = 'supervisor'
        session.permanent = True
        return jsonify({'redirect': '/master'})
    
    cliente = Cliente.query.filter_by(correo=email).first()
    if cliente and check_password_hash(cliente.password_hash, password):
        session['user_id'] = cliente.id
        session['tipo'] = 'cliente'
        session.permanent = True
        return jsonify({'redirect': '/app'})
    
    perfil = Perfil.query.filter_by(correo=email).first()
    if perfil and check_password_hash(perfil.password_hash, password):
        session['perfil_id'] = perfil.id
        session['tipo'] = 'modelo'
        session.permanent = True
        perfil.is_online = True
        perfil.ultima_conexion = datetime.utcnow()
        perfil.ultima_ip = request.remote_addr
        registrar_log_conexion(perfil.id, 'login', request.remote_addr)
        db.session.commit()
        return jsonify({'redirect': f'/operador/{perfil.id}'})
    
    agencia = Agencia.query.filter_by(correo=email).first()
    if agencia and check_password_hash(agencia.password_hash, password):
        session['agencia_id'] = agencia.id
        session['tipo'] = 'agencia'
        session.permanent = True
        return jsonify({'redirect': f'/dashboard/{agencia.id}'})
    
    return jsonify({'msg': 'Credenciales incorrectas'}), 401

@app.route('/logout')
def logout():
    if session.get('tipo') == 'modelo' and session.get('perfil_id'):
        perfil = Perfil.query.get(session['perfil_id'])
        if perfil:
            perfil.is_online = False
            registrar_log_conexion(perfil.id, 'logout', request.remote_addr)
            db.session.commit()
    session.clear()
    return redirect('/')

# ============================
# RUTAS SUPERADMIN & AGENCIA
# ============================
@app.route('/master')
@superadmin_required
def master():
    agencias = Agencia.query.all()
    return render_template('supervisor.html', agencias=agencias)

@app.route('/superadmin/config')
@superadmin_required
def superadmin_config():
    rates = Rate.query.all()
    return render_template('superadmin_config.html', rates=rates)

@app.route('/api/update_rate', methods=['POST'])
@superadmin_required
def api_update_rate():
    data = request.get_json()
    rate = Rate.query.get(data.get('id'))
    if rate:
        rate.creditos_costo = int(data.get('costo_creditos', 1))
        rate.creditos_ganancia_modelo = int(data.get('ganancia_modelo', 1))
        rate.valor_usd = float(data.get('valor_usd', 0.10))
        rate.activo = data.get('activo', True)
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False}), 404

@app.route('/api/crear_agencia', methods=['POST'])
@superadmin_required
def api_crear_agencia():
    data = request.get_json()
    if Agencia.query.filter_by(correo=data['correo']).first():
        return jsonify({'success': False, 'msg': 'El correo ya existe'}), 400
    nueva = Agencia(
        nombre=data['nombre'],
        correo=data['correo'],
        password_hash=generate_password_hash(data['password']),
        comision=int(data.get('comision', 50)),
        pais=data.get('pais', 'No especificado')
    )
    db.session.add(nueva)
    db.session.commit()
    return jsonify({'success': True, 'id': nueva.id})

@app.route('/api/eliminar_agencia/<int:agencia_id>', methods=['DELETE'])
@superadmin_required
def api_eliminar_agencia(agencia_id):
    agencia = Agencia.query.get_or_404(agencia_id)
    db.session.delete(agencia)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/gestionar/<int:agencia_id>')
@superadmin_required
def gestionar(agencia_id):
    agencia = Agencia.query.get_or_404(agencia_id)
    return render_template('gestionar.html', agencia=agencia)

@app.route('/api/crear_perfil', methods=['POST'])
@superadmin_required
def api_crear_perfil():
    nombre = request.form.get('nombre')
    correo = request.form.get('correo')
    password = request.form.get('password')
    agencia_id = request.form.get('agencia_id')
    
    if Perfil.query.filter_by(correo=correo).first():
        return jsonify({'success': False, 'msg': 'El correo ya existe'}), 400
        
    foto_filename = 'default_user.png'
    if 'foto' in request.files:
        file = request.files['foto']
        if file and file.filename:
            ext = file.filename.rsplit('.', 1)[-1].lower()
            foto_filename = secure_filename(f"perfil_{uuid.uuid4().hex[:8]}.{ext}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_filename))
            
    doc_filename = None
    if 'documento' in request.files:
        doc_file = request.files['documento']
        if doc_file and doc_file.filename:
            ext = doc_file.filename.rsplit('.', 1)[-1].lower()
            doc_filename = secure_filename(f"kyc_{uuid.uuid4().hex[:8]}.{ext}")
            doc_file.save(os.path.join('static/uploads/kyc', doc_filename))
            
    nuevo_perfil = Perfil(
        nombre=nombre,
        correo=correo,
        password_hash=generate_password_hash(password),
        agencia_id=agencia_id,
        foto_principal=foto_filename,
        foto_portada=foto_filename,
        is_online=False,
        verificado=False,
        documento_identidad=doc_filename
    )
    db.session.add(nuevo_perfil)
    db.session.commit()
    return jsonify({'success': True, 'id': nuevo_perfil.id})

@app.route('/api/eliminar_perfil/<int:perfil_id>', methods=['DELETE'])
@superadmin_required
def api_eliminar_perfil(perfil_id):
    perfil = Perfil.query.get_or_404(perfil_id)
    db.session.delete(perfil)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/monitor_chat')
@superadmin_required
def monitor_chat():
    return render_template('chat_monitor.html')

@app.route('/reportes')
@superadmin_required
def reportes():
    agencias = Agencia.query.all()
    return render_template('reportes.html', agencias=agencias)

@app.route('/api/generar_reporte', methods=['POST'])
@superadmin_required
def api_generar_reporte():
    data = request.get_json()
    agencia_id = data.get('agencia_id')
    fecha_inicio = data.get('fecha_inicio')
    fecha_fin = data.get('fecha_fin')
    
    query = db.session.query(db.func.sum(Perfil.creditos_generados)).join(Agencia, Perfil.agencia_id == Agencia.id)
    if agencia_id:
        query = query.filter(Agencia.id == agencia_id)
    
    total_creditos = query.scalar() or 0
    rate = obtener_rate('chat')
    monto = total_creditos * rate.valor_usd
    
    return jsonify({'success': True, 'creditos': total_creditos, 'monto': monto})

@app.route('/dashboard/<int:agencia_id>')
@agencia_required
def dashboard_agencia(agencia_id):
    if session.get('agencia_id') != agencia_id:
        abort(403)
    agencia = Agencia.query.get_or_404(agencia_id)
    total_creditos = sum(p.creditos_generados for p in agencia.perfiles)
    online_count = sum(1 for p in agencia.perfiles if p.is_online)
    return render_template('agencia.html', agencia=agencia, total_creditos=total_creditos, online_count=online_count)

# ============================
# RUTAS DE CLIENTE
# ============================
@app.route('/app')
@login_required
def app_main():
    if session.get('tipo') != 'cliente': 
        return redirect('/')
    cliente = Cliente.query.get(session['user_id'])
    perfiles = Perfil.query.filter(
        Perfil.edad >= cliente.edad_min, 
        Perfil.edad <= cliente.edad_max
    ).all()
    return render_template('usuario.html', cliente=cliente, perfiles=perfiles)

@app.route('/perfil_cliente')
@login_required
def perfil_cliente():
    if session.get('tipo') != 'cliente': 
        return redirect('/')
    cliente = Cliente.query.get(session['user_id'])
    galeria = ClienteFoto.query.filter_by(cliente_id=cliente.id).order_by(ClienteFoto.fecha_subida.desc()).all()
    return render_template('perfil_cliente_v2.html', cliente=cliente, galeria=galeria)

@app.route('/chat_cliente/<int:perfil_id>')
@login_required
def chat_cliente(perfil_id):
    if session.get('tipo') != 'cliente': 
        return redirect('/')
    
    cliente = Cliente.query.get(session['user_id'])
    perfil = Perfil.query.get_or_404(perfil_id)
    
    fotos = Foto.query.filter_by(perfil_id=perfil_id).all()
    perfil.fotos = fotos
    
    if not perfil.foto_portada or perfil.foto_portada == 'default_cover.png':
        perfil.foto_portada = perfil.foto_principal
    
    if not perfil.biografia:
        perfil.biografia = 'Hola! Encantada de conocerte 💕'
    if not perfil.estado_hoy:
        perfil.estado_hoy = '✨ Disponible para chatear ✨'
    if not perfil.intereses:
        perfil.intereses = 'Música, Viajes, Café'
    
    return render_template('chat_cliente_ws.html', cliente=cliente, perfil=perfil)

@app.route('/ver_perfil_modelo/<int:perfil_id>')
@login_required
def ver_perfil_modelo(perfil_id):
    if session.get('tipo') != 'cliente': 
        return redirect('/')
    perfil = Perfil.query.get_or_404(perfil_id)
    stats = {
        'chats_activos': Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id)
        ).distinct().count(),
        'favoritos': Favorito.query.filter_by(perfil_id=perfil.id).count(),
        'mensajes_hoy': Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= datetime.utcnow().replace(hour=0, minute=0, second=0)
        ).count(),
        'creditos_hoy': 0,
        'creditos_semana': 0,
        'creditos_mes': 0
    }
    return render_template('perfil_modelo.html', perfil=perfil, stats=stats)

@app.route('/embed_perfil_modelo/<int:perfil_id>')
@login_required
def embed_perfil_modelo(perfil_id):
    if session.get('tipo') != 'cliente':
        return redirect('/')
    perfil = Perfil.query.get_or_404(perfil_id)
    return render_template('perfil_modelo_embed.html', perfil=perfil)

@app.route('/api/cliente/subir_foto', methods=['POST'])
@login_required
def api_cliente_subir_foto():
    if session.get('tipo') != 'cliente':
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    if 'foto' not in request.files:
        return jsonify({'success': False, 'msg': 'No se envió ninguna foto'}), 400
    
    file = request.files['foto']
    if file.filename == '':
        return jsonify({'success': False, 'msg': 'Archivo vacío'}), 400
    
    cliente = Cliente.query.get(session['user_id'])
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
    filename = secure_filename(f"cliente_{cliente.id}_{uuid.uuid4().hex[:8]}.{ext}")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    nueva_foto = ClienteFoto(cliente_id=cliente.id, ruta=filename)
    db.session.add(nueva_foto)
    db.session.commit()
    
    return jsonify({'success': True, 'foto_id': nueva_foto.id, 'ruta': filename})

@app.route('/api/cliente/foto_principal', methods=['POST'])
@login_required
def api_cliente_foto_principal():
    if session.get('tipo') != 'cliente':
        return jsonify({'success': False}), 403
    
    data = request.get_json()
    foto_id = data.get('foto_id')
    cliente = Cliente.query.get(session['user_id'])
    
    if foto_id:
        foto = ClienteFoto.query.get(foto_id)
        if foto and foto.cliente_id == cliente.id:
            cliente.foto_perfil = foto.ruta
            db.session.commit()
            return jsonify({'success': True})
    else:
        cliente.foto_perfil = 'default_user.png'
        db.session.commit()
        return jsonify({'success': True})
    
    return jsonify({'success': False}), 400

@app.route('/api/cliente/eliminar_foto/<int:foto_id>', methods=['DELETE'])
@login_required
def api_cliente_eliminar_foto(foto_id):
    if session.get('tipo') != 'cliente':
        return jsonify({'success': False}), 403
    
    foto = ClienteFoto.query.get_or_404(foto_id)
    cliente = Cliente.query.get(session['user_id'])
    
    if foto.cliente_id != cliente.id:
        return jsonify({'success': False}), 403
    
    if cliente.foto_perfil == foto.ruta:
        otra_foto = ClienteFoto.query.filter(ClienteFoto.cliente_id == cliente.id, ClienteFoto.id != foto_id).first()
        if otra_foto:
            cliente.foto_perfil = otra_foto.ruta
        else:
            cliente.foto_perfil = 'default_user.png'
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], foto.ruta)
    if os.path.exists(filepath) and foto.ruta != 'default_user.png':
        os.remove(filepath)
    
    db.session.delete(foto)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/api/perfil/editar_full', methods=['POST'])
@login_required
def api_editar_perfil_full():
    if session.get('tipo') != 'cliente':
        return jsonify({'success': False}), 403
    
    cliente = Cliente.query.get(session['user_id'])
    
    if request.form.get('nombre'):
        cliente.nombre_real = request.form.get('nombre')
    if request.form.get('edad'):
        cliente.edad = int(request.form.get('edad'))
    if request.form.get('pais'):
        cliente.pais = request.form.get('pais')
    if request.form.get('estado'):
        cliente.estado = request.form.get('estado')
    if request.form.get('genero'):
        cliente.genero = request.form.get('genero')
    if request.form.get('orientacion_sexual'):
        cliente.orientacion_sexual = request.form.get('orientacion_sexual')
    if request.form.get('busco'):
        cliente.busco = request.form.get('busco')
    if request.form.get('edad_min'):
        cliente.edad_min = int(request.form.get('edad_min'))
    if request.form.get('edad_max'):
        cliente.edad_max = int(request.form.get('edad_max'))
    if request.form.get('intencion'):
        cliente.intencion = request.form.get('intencion')
    if request.form.get('estado_civil'):
        cliente.estado_civil = request.form.get('estado_civil')
    if request.form.get('trabajo'):
        cliente.trabajo = request.form.get('trabajo')
    if request.form.get('educacion'):
        cliente.educacion = request.form.get('educacion')
    if request.form.get('estado_hoy'):
        cliente.estado_hoy = request.form.get('estado_hoy')
    if request.form.get('bio'):
        cliente.biografia = request.form.get('bio')
    if request.form.get('intereses'):
        cliente.intereses = request.form.get('intereses')
    if request.form.get('estatura'):
        cliente.estatura = request.form.get('estatura')
    if request.form.get('color_piel'):
        cliente.color_piel = request.form.get('color_piel')
    if request.form.get('habitos'):
        cliente.habitos = request.form.get('habitos')
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/cliente/comprar_foto', methods=['POST'])
@login_required
def api_comprar_foto():
    if session.get('tipo') != 'cliente':
        return jsonify({'success': False})
    data = request.get_json()
    foto_id = data.get('foto_id')
    cliente = Cliente.query.get(session['user_id'])
    foto = Foto.query.get(foto_id)
    if not foto:
        return jsonify({'success': False, 'msg': 'Foto no encontrada'})
    
    ya_comprada = FotoComprada.query.filter_by(cliente_id=cliente.id, foto_id=foto.id).first()
    if ya_comprada:
        return jsonify({'success': True})
    
    if cliente.creditos < foto.costo:
        return jsonify({'success': False, 'msg': 'Saldo insuficiente'})
        
    cliente.creditos -= foto.costo
    perfil = Perfil.query.get(foto.perfil_id)
    perfil.creditos_generados += foto.costo
    
    compra = FotoComprada(cliente_id=cliente.id, foto_id=foto.id)
    db.session.add(compra)
    db.session.commit()
    return jsonify({'success': True, 'creditos': cliente.creditos})

@app.route('/api/comprar_creditos', methods=['POST'])
@login_required
def comprar_creditos():
    if session.get('tipo') != 'cliente':
        return jsonify({'success': False})
    cliente = Cliente.query.get(session['user_id'])
    cliente.creditos += 100
    db.session.commit()
    return jsonify({'success': True, 'creditos': cliente.creditos})

@app.route('/api/cobrar_chat', methods=['POST'])
@login_required
def cobrar_chat():
    if session.get('tipo') != 'cliente':
        return jsonify({'success': False})
    cliente = Cliente.query.get(session['user_id'])
    rate = obtener_rate('chat')
    if cliente.creditos >= rate.creditos_costo:
        return jsonify({'success': True})
    return jsonify({'success': False, 'msg': 'Saldo insuficiente'})

@app.route('/api/favorito/toggle', methods=['POST'])
@login_required
def toggle_fav():
    data = request.get_json()
    para_id = data.get('para_id')
    
    if session.get('tipo') == 'cliente':
        cliente_id = session['user_id']
        perfil_id = para_id
    else:
        cliente_id = para_id
        perfil_id = session['perfil_id']
        
    fav = Favorito.query.filter_by(cliente_id=cliente_id, perfil_id=perfil_id).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({'status': 'removed', 'match': False})
    else:
        nuevo_fav = Favorito(cliente_id=cliente_id, perfil_id=perfil_id)
        db.session.add(nuevo_fav)
        db.session.commit()
        otro_fav = Favorito.query.filter_by(cliente_id=perfil_id, perfil_id=cliente_id).first()
        if otro_fav:
            nuevo_fav.es_match = True
            otro_fav.es_match = True
            db.session.commit()
            return jsonify({'status': 'added', 'match': True})
        return jsonify({'status': 'added', 'match': False})

# ============================
# RUTAS DE MODELO
# ============================
@app.route('/operador/<int:perfil_id>')
@modelo_required
def operador(perfil_id):
    if session.get('perfil_id') != perfil_id:
        abort(403)
    perfil = Perfil.query.get_or_404(perfil_id)
    cliente_id = request.args.get('cliente', type=int)
    
    perfil.is_online = True
    perfil.ultima_conexion = datetime.utcnow()
    perfil.ultima_ip = request.remote_addr
    db.session.commit()
    
    cliente_actual = Cliente.query.get(cliente_id) if cliente_id else None
    
    hoy = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    semana = datetime.utcnow() - timedelta(days=7)
    mes = datetime.utcnow() - timedelta(days=30)
    
    stats = {
        'chats_activos': Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id)
        ).distinct().count(),
        'favoritos': Favorito.query.filter_by(perfil_id=perfil.id).count(),
        'mensajes_hoy': Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= hoy
        ).count(),
        'creditos_hoy': Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= hoy
        ).with_entities(func.sum(Mensaje.creditos_generados)).scalar() or 0,
        'creditos_semana': Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= semana
        ).with_entities(func.sum(Mensaje.creditos_generados)).scalar() or 0,
        'creditos_mes': Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= mes
        ).with_entities(func.sum(Mensaje.creditos_generados)).scalar() or 0
    }
    
    return render_template('chat_modelo_ws.html', perfil=perfil, cliente_actual=cliente_actual, stats=stats)

@app.route('/perfil_modelo')
@modelo_required
def perfil_modelo():
    perfil = Perfil.query.get(session['perfil_id'])
    stats = {
        'chats_activos': Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id)
        ).distinct().count(),
        'favoritos': Favorito.query.filter_by(perfil_id=perfil.id).count(),
        'mensajes_hoy': Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= datetime.utcnow().replace(hour=0, minute=0, second=0)
        ).count(),
        'creditos_hoy': 0,
        'creditos_semana': 0,
        'creditos_mes': 0
    }
    return render_template('perfil_modelo.html', perfil=perfil, stats=stats)

@app.route('/api/perfil_modelo/actualizar', methods=['POST'])
@modelo_required
def api_actualizar_perfil_modelo():
    perfil = Perfil.query.get(session['perfil_id'])
    
    if request.form.get('nombre'):
        perfil.nombre = request.form.get('nombre')
    if request.form.get('estado_hoy'):
        perfil.estado_hoy = request.form.get('estado_hoy')
    if request.form.get('biografia'):
        perfil.biografia = request.form.get('biografia')
    if request.form.get('ubicacion'):
        perfil.ubicacion = request.form.get('ubicacion')
    if request.form.get('edad'):
        perfil.edad = int(request.form.get('edad'))
    if request.form.get('signo'):
        perfil.signo = request.form.get('signo')
    if request.form.get('idiomas'):
        perfil.idiomas = request.form.get('idiomas')
    if request.form.get('intereses'):
        perfil.intereses = request.form.get('intereses')
    if request.form.get('edad_min'):
        perfil.edad_min = int(request.form.get('edad_min'))
    if request.form.get('edad_max'):
        perfil.edad_max = int(request.form.get('edad_max'))
    if request.form.get('buscando_desc'):
        perfil.buscando_desc = request.form.get('buscando_desc')
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/perfil_modelo/subir_foto', methods=['POST'])
@modelo_required
def api_perfil_modelo_subir_foto():
    if 'foto' not in request.files:
        return jsonify({'success': False, 'msg': 'No se envió ninguna foto'}), 400
    
    file = request.files['foto']
    if file.filename == '':
        return jsonify({'success': False, 'msg': 'Archivo vacío'}), 400
    
    perfil = Perfil.query.get(session['perfil_id'])
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
    filename = secure_filename(f"modelo_{perfil.id}_{uuid.uuid4().hex[:8]}.{ext}")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    nueva_foto = Foto(perfil_id=perfil.id, ruta=filename, es_privada=False)
    db.session.add(nueva_foto)
    db.session.commit()
    
    return jsonify({'success': True, 'foto_id': nueva_foto.id, 'ruta': filename})

@app.route('/api/perfil_modelo/foto_principal', methods=['POST'])
@modelo_required
def api_perfil_modelo_foto_principal():
    data = request.get_json()
    foto_id = data.get('foto_id')
    perfil = Perfil.query.get(session['perfil_id'])
    
    if foto_id:
        foto = Foto.query.get(foto_id)
        if foto and foto.perfil_id == perfil.id:
            perfil.foto_principal = foto.ruta
            db.session.commit()
            
            socketio.emit('perfil_actualizado', {
                'perfil_id': perfil.id,
                'tipo': 'foto',
                'valor': foto.ruta,
                'tiene_portada_personalizada': perfil.foto_portada != perfil.foto_principal
            }, room=f"modelo_{perfil.id}")
            
            return jsonify({'success': True})
    return jsonify({'success': False}), 400

@app.route('/api/perfil_modelo/eliminar_foto/<int:foto_id>', methods=['DELETE'])
@modelo_required
def api_perfil_modelo_eliminar_foto(foto_id):
    foto = Foto.query.get_or_404(foto_id)
    perfil = Perfil.query.get(session['perfil_id'])
    
    if foto.perfil_id != perfil.id:
        return jsonify({'success': False}), 403
    
    if perfil.foto_principal == foto.ruta:
        otra_foto = Foto.query.filter(Foto.perfil_id == perfil.id, Foto.id != foto_id).first()
        if otra_foto:
            perfil.foto_principal = otra_foto.ruta
        else:
            perfil.foto_principal = 'default_user.png'
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], foto.ruta)
    if os.path.exists(filepath) and foto.ruta != 'default_user.png':
        os.remove(filepath)
    
    db.session.delete(foto)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/api/modelo/subir_portada', methods=['POST'])
@modelo_required
def api_modelo_subir_portada():
    if 'portada' not in request.files:
        return jsonify({'success': False, 'msg': 'No se envió ninguna imagen'}), 400
    
    file = request.files['portada']
    if file.filename == '':
        return jsonify({'success': False, 'msg': 'Archivo vacío'}), 400
    
    perfil = Perfil.query.get(session['perfil_id'])
    
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
    filename = secure_filename(f"portada_{perfil.id}_{uuid.uuid4().hex[:8]}.{ext}")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    if perfil.foto_portada and perfil.foto_portada != 'default_cover.png':
        old_path = os.path.join(app.config['UPLOAD_FOLDER'], perfil.foto_portada)
        if os.path.exists(old_path):
            os.remove(old_path)
    
    perfil.foto_portada = filename
    db.session.commit()
    
    socketio.emit('portada_actualizada', {
        'perfil_id': perfil.id,
        'portada_url': filename,
        'timestamp': datetime.utcnow().isoformat()
    }, room=f"modelo_{perfil.id}")
    
    return jsonify({
        'success': True, 
        'ruta': filename,
        'url': f"/static/uploads/{filename}"
    })

@app.route('/api/modelo/eliminar_portada', methods=['DELETE'])
@modelo_required
def api_modelo_eliminar_portada():
    perfil = Perfil.query.get(session['perfil_id'])
    
    if perfil.foto_portada and perfil.foto_portada != 'default_cover.png':
        old_path = os.path.join(app.config['UPLOAD_FOLDER'], perfil.foto_portada)
        if os.path.exists(old_path):
            os.remove(old_path)
    
    perfil.foto_portada = perfil.foto_principal
    db.session.commit()
    
    socketio.emit('portada_actualizada', {
        'perfil_id': perfil.id,
        'portada_url': perfil.foto_principal,
        'timestamp': datetime.utcnow().isoformat()
    }, room=f"modelo_{perfil.id}")
    
    return jsonify({'success': True, 'portada_url': perfil.foto_principal})

@app.route('/api/toggle_online', methods=['POST'])
@modelo_required
def api_toggle_online():
    perfil = Perfil.query.get(session['perfil_id'])
    perfil.is_online = not perfil.is_online
    db.session.commit()
    return jsonify({'success': True, 'is_online': perfil.is_online})

@app.route('/api/mis_ganancias/<int:perfil_id>')
@login_required
def api_ganancias(perfil_id):
    perfil = Perfil.query.get(perfil_id)
    return jsonify({'ganancias': perfil.creditos_generados if perfil else 0})

# ============================
# APIS COMPARTIDAS (CHATS)
# ============================
@app.route('/api/mis_conversaciones')
@login_required
def mis_conversaciones():
    if session.get('tipo') == 'cliente':
        cliente = Cliente.query.get(session['user_id'])
        mensajes = Mensaje.query.filter((Mensaje.emisor_cliente_id == cliente.id) | (Mensaje.receptor_cliente_id == cliente.id)).all()
        ids = list(set([m.receptor_perfil_id if m.emisor_cliente_id == cliente.id else m.emisor_perfil_id for m in mensajes]))
        contactos = []
        for pid in ids:
            if pid:
                p = Perfil.query.get(pid)
                if p:
                    contactos.append({
                        'id': p.id, 
                        'nombre': p.nombre, 
                        'foto': p.foto_principal, 
                        'estado': p.estado_hoy, 
                        'is_online': p.is_online
                    })
        return jsonify(contactos)
        
    elif session.get('tipo') == 'modelo':
        perfil = Perfil.query.get(session['perfil_id'])
        mensajes = Mensaje.query.filter((Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id)).all()
        ids = list(set([m.receptor_cliente_id if m.emisor_perfil_id == perfil.id else m.emisor_cliente_id for m in mensajes]))
        contactos = []
        for cid in ids:
            if cid:
                c = Cliente.query.get(cid)
                if c:
                    contactos.append({
                        'id': c.id, 
                        'nombre': c.nombre_real, 
                        'foto': c.foto_perfil, 
                        'estado': c.estado_hoy, 
                        'is_online': True
                    })
        return jsonify(contactos)
    return jsonify([])

@app.route('/api/enviar_mensaje', methods=['POST'])
@login_required
def api_enviar_mensaje():
    data = request.get_json()
    contenido = data.get('contenido', '').strip()
    receptor_id = data.get('receptor_id')
    
    if not contenido or not receptor_id:
        return jsonify({'success': False, 'msg': 'Datos incompletos'}), 400
    
    es_scam, motivo = detectar_scam(contenido)
    if es_scam: 
        return jsonify({'success': False, 'msg': motivo}), 403
        
    if session.get('tipo') == 'cliente':
        cliente = Cliente.query.get(session['user_id'])
        perfil = Perfil.query.get(receptor_id)
        rate = obtener_rate('chat')
        
        if cliente.creditos < rate.creditos_costo:
            return jsonify({'success': False, 'msg': 'Sin créditos suficientes'}), 403
            
        mensaje = Mensaje(
            contenido=contenido, 
            tipo_emisor='cliente', 
            emisor_cliente_id=cliente.id, 
            receptor_perfil_id=perfil.id, 
            creditos_generados=rate.creditos_ganancia_modelo
        )
        cliente.creditos -= rate.creditos_costo
        perfil.creditos_generados += rate.creditos_ganancia_modelo
        db.session.add(mensaje)
        db.session.commit()
        
        sala_chat = f"modelo_{perfil.id}"
        msg_data = {
            'id': mensaje.id, 
            'contenido': contenido, 
            'tipo_emisor': 'cliente', 
            'timestamp': mensaje.fecha.isoformat()
        }
        socketio.emit('nuevo_mensaje', msg_data, room=sala_chat)
        socketio.emit('monitor_mensaje', {
            **msg_data, 
            'agencia_id': perfil.agencia_id, 
            'perfil_nombre': perfil.nombre, 
            'cliente_nombre': cliente.nombre_real
        }, room='superadmin_monitor')
        
        return jsonify({'success': True, 'balance': cliente.creditos, 'mensaje_id': mensaje.id})
        
    elif session.get('tipo') == 'modelo':
        perfil = Perfil.query.get(session['perfil_id'])
        cliente = Cliente.query.get(receptor_id)
        mensaje = Mensaje(
            contenido=contenido, 
            tipo_emisor='modelo', 
            emisor_perfil_id=perfil.id, 
            receptor_cliente_id=cliente.id, 
            creditos_generados=0
        )
        db.session.add(mensaje)
        db.session.commit()
        
        sala_chat = f"modelo_{perfil.id}"
        msg_data = {
            'id': mensaje.id, 
            'contenido': contenido, 
            'tipo_emisor': 'modelo', 
            'timestamp': mensaje.fecha.isoformat()
        }
        socketio.emit('nuevo_mensaje', msg_data, room=sala_chat)
        socketio.emit('monitor_mensaje', {
            **msg_data, 
            'agencia_id': perfil.agencia_id, 
            'perfil_nombre': perfil.nombre, 
            'cliente_nombre': cliente.nombre_real
        }, room='superadmin_monitor')
        
        return jsonify({'success': True, 'mensaje_id': mensaje.id})
        
    return jsonify({'success': False}), 403

@app.route('/api/get_mensajes/<int:contacto_id>')
@login_required
def api_get_mensajes(contacto_id):
    if session.get('tipo') == 'cliente':
        mensajes = Mensaje.query.filter(
            ((Mensaje.emisor_cliente_id == session['user_id']) & (Mensaje.receptor_perfil_id == contacto_id)) |
            ((Mensaje.emisor_perfil_id == contacto_id) & (Mensaje.receptor_cliente_id == session['user_id']))
        ).order_by(Mensaje.fecha.asc()).all()
    elif session.get('tipo') == 'modelo':
        mensajes = Mensaje.query.filter(
            ((Mensaje.emisor_perfil_id == session['perfil_id']) & (Mensaje.receptor_cliente_id == contacto_id)) |
            ((Mensaje.emisor_cliente_id == contacto_id) & (Mensaje.receptor_perfil_id == session['perfil_id']))
        ).order_by(Mensaje.fecha.asc()).all()
    else:
        return jsonify([])
        
    return jsonify([{
        'id': m.id, 
        'contenido': m.contenido, 
        'fecha': m.fecha.isoformat(), 
        'tipo_emisor': m.tipo_emisor
    } for m in mensajes])

# ============================
# WEBSOCKETS (EVENTOS)
# ============================
@socketio.on('join')
def handle_join(data):
    room = data.get('room')
    if room:
        join_room(room)

@socketio.on('join_monitor')
def handle_join_monitor():
    if session.get('tipo') == 'supervisor':
        join_room('superadmin_monitor')

@socketio.on('escribiendo')
def handle_escribiendo(data):
    receptor_id = data.get('receptor_id')
    room = f"modelo_{receptor_id}" if session.get('tipo') == 'cliente' else f"modelo_{session.get('perfil_id')}"
    emit('escribiendo', {'emisor_id': session.get('user_id') or session.get('perfil_id')}, room=room, include_self=False)

@socketio.on('enviar_regalo')
def handle_regalo(data):
    if session.get('tipo') != 'cliente':
        return
    room = data.get('room')
    regalo = data.get('regalo')
    costo = int(data.get('costo', 10))
    receptor_id = data.get('receptor_id')
    
    cliente = Cliente.query.get(session['user_id'])
    perfil = Perfil.query.get(receptor_id)
    
    if cliente and perfil and cliente.creditos >= costo:
        cliente.creditos -= costo
        perfil.creditos_generados += costo
        db.session.commit()
        
        emit('recibir_regalo', {'regalo': regalo, 'emisor': cliente.nombre_real}, room=room)
        emit('actualizar_balance', {'creditos': cliente.creditos}, to=request.sid)

@socketio.on('reaccion_mensaje')
def handle_reaccion(data):
    emit('nueva_reaccion', data, room=data.get('room'))

@socketio.on('lets_mingle')
def handle_lets_mingle(data):
    if session.get('tipo') != 'modelo':
        return
    perfil = Perfil.query.get(session['perfil_id'])
    solicitud = {
        'modelo_id': perfil.id,
        'nombre': perfil.nombre,
        'foto': perfil.foto_principal,
        'estado': perfil.estado_hoy
    }
    emit('nueva_solicitud_mingle', solicitud, broadcast=True)

@socketio.on('modelo_actualizo_portada')
def handle_modelo_actualizo_portada(data):
    perfil_id = data.get('perfil_id')
    portada_url = data.get('portada_url')
    room = f"modelo_{perfil_id}"
    emit('portada_actualizada', {
        'perfil_id': perfil_id,
        'portada_url': portada_url,
        'timestamp': datetime.utcnow().isoformat()
    }, room=room)

@socketio.on('perfil_actualizado')
def handle_perfil_actualizado(data):
    room = f"modelo_{data.get('perfil_id')}"
    emit('perfil_actualizado', data, room=room)

# ============================
# INICIO DE LA APLICACIÓN
# ============================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_rates()
        # Crear superadmin si no existe
        if not Agencia.query.filter_by(correo='master@amura.com').first():
            admin = Agencia(
                nombre='Master Admin',
                correo='master@amura.com',
                password_hash=generate_password_hash('master123'),
                comision=0,
                pais='Admin'
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ Superadmin creado: master@amura.com / master123")
    
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
