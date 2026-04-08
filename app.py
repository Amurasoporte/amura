from flask import Flask, render_template, request, jsonify, session, redirect, abort
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import uuid
import re
import json
from functools import wraps
from sqlalchemy import func

app = Flask(__name__)

# ========== CONFIGURACIÓN ==========
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'amura-secret-key-2024-cambiar-en-produccion')
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

if os.environ.get('DATABASE_URL'):
    database_url = os.environ.get('DATABASE_URL')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///amura.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static/uploads/kyc', exist_ok=True)

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ============================
# DECORADORES
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
# MODELOS
# ============================

class Admin(db.Model):
    __tablename__ = 'admin'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LogAdmin(db.Model):
    __tablename__ = 'log_admin'
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, nullable=True)
    admin_nombre = db.Column(db.String(100), nullable=True)
    admin_email = db.Column(db.String(100), nullable=True)
    accion = db.Column(db.String(100), nullable=False)
    detalles = db.Column(db.Text, nullable=True)
    ip = db.Column(db.String(50), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

class LogLoginFallido(db.Model):
    __tablename__ = 'log_login_fallido'
    id = db.Column(db.Integer, primary_key=True)
    email_intentado = db.Column(db.String(100), nullable=False)
    ip = db.Column(db.String(50), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

class ConfigGlobal(db.Model):
    __tablename__ = 'config_global'
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @staticmethod
    def get(clave, default=None):
        config = ConfigGlobal.query.filter_by(clave=clave).first()
        if config:
            return config.valor
        return default
    
    @staticmethod
    def set(clave, valor, descripcion=None):
        config = ConfigGlobal.query.filter_by(clave=clave).first()
        if config:
            config.valor = valor
            if descripcion:
                config.descripcion = descripcion
        else:
            config = ConfigGlobal(clave=clave, valor=valor, descripcion=descripcion)
            db.session.add(config)
        db.session.commit()
        return config

class Regalo(db.Model):
    __tablename__ = 'regalo'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    costo_creditos = db.Column(db.Integer, nullable=False, default=10)
    imagen_url = db.Column(db.String(500), nullable=True)
    activo = db.Column(db.Boolean, default=True)
    orden = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'emoji': self.emoji,
            'costo_creditos': self.costo_creditos,
            'imagen_url': self.imagen_url,
            'activo': self.activo,
            'orden': self.orden
        }

class Agencia(db.Model):
    __tablename__ = 'agencia'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(20), unique=True, nullable=True)
    nombre = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    comision_agencia = db.Column(db.Integer, default=25)
    comision_plataforma = db.Column(db.Integer, default=60)
    comision_modelo = db.Column(db.Integer, default=15)
    pais = db.Column(db.String(100), default='No especificado')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    perfiles = db.relationship('Perfil', backref='agencia', lazy=True, cascade='all, delete-orphan')
    
    @property
    def comision(self):
        return self.comision_agencia
    
    @comision.setter
    def comision(self, valor):
        self.comision_agencia = valor
    
    def generate_public_id(self):
        ultima = Agencia.query.filter(Agencia.public_id.isnot(None)).order_by(Agencia.id.desc()).first()
        if ultima and ultima.public_id:
            try:
                num = int(ultima.public_id[1:]) + 1
                return f"A{num}"
            except:
                pass
        return "A1001"

class AgenciaBono(db.Model):
    __tablename__ = 'agencia_bono'
    id = db.Column(db.Integer, primary_key=True)
    agencia_id = db.Column(db.Integer, db.ForeignKey('agencia.id'), nullable=False, unique=True)
    bono_activo = db.Column(db.Boolean, default=True)
    bono_porcentaje = db.Column(db.Integer, default=5)
    meta_diaria_creditos = db.Column(db.Integer, default=1000)
    meta_diaria_usd = db.Column(db.Float, default=100.0)
    leaderboard_activo = db.Column(db.Boolean, default=True)
    premio_primer_lugar = db.Column(db.Integer, default=10)
    premio_segundo_lugar = db.Column(db.Integer, default=5)
    premio_tercer_lugar = db.Column(db.Integer, default=3)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PremioLeaderboard(db.Model):
    __tablename__ = 'premio_leaderboard'
    id = db.Column(db.Integer, primary_key=True)
    agencia_id = db.Column(db.Integer, db.ForeignKey('agencia.id'), nullable=False, unique=True)
    
    semanal_activo = db.Column(db.Boolean, default=True)
    semanal_premio1 = db.Column(db.Float, default=50.0)
    semanal_premio2 = db.Column(db.Float, default=30.0)
    semanal_premio3 = db.Column(db.Float, default=20.0)
    semanal_objetivo = db.Column(db.Integer, default=0)
    semanal_ultimo_cierre = db.Column(db.DateTime, nullable=True)
    semanal_inicio_periodo = db.Column(db.DateTime, nullable=True)
    
    quincenal_activo = db.Column(db.Boolean, default=False)
    quincenal_premio1 = db.Column(db.Float, default=100.0)
    quincenal_premio2 = db.Column(db.Float, default=60.0)
    quincenal_premio3 = db.Column(db.Float, default=40.0)
    quincenal_objetivo = db.Column(db.Integer, default=0)
    quincenal_ultimo_cierre = db.Column(db.DateTime, nullable=True)
    quincenal_inicio_periodo = db.Column(db.DateTime, nullable=True)
    
    mensual_activo = db.Column(db.Boolean, default=True)
    mensual_premio1 = db.Column(db.Float, default=200.0)
    mensual_premio2 = db.Column(db.Float, default=120.0)
    mensual_premio3 = db.Column(db.Float, default=80.0)
    mensual_objetivo = db.Column(db.Integer, default=0)
    mensual_ultimo_cierre = db.Column(db.DateTime, nullable=True)
    mensual_inicio_periodo = db.Column(db.DateTime, nullable=True)
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    agencia = db.relationship('Agencia', backref='config_premios')

class GastoPremio(db.Model):
    __tablename__ = 'gasto_premio'
    id = db.Column(db.Integer, primary_key=True)
    agencia_id = db.Column(db.Integer, db.ForeignKey('agencia.id'), nullable=False)
    perfil_id = db.Column(db.Integer, db.ForeignKey('perfil.id'), nullable=False)
    periodo = db.Column(db.String(20))
    fecha_inicio = db.Column(db.DateTime, nullable=False)
    fecha_fin = db.Column(db.DateTime, nullable=False)
    puesto = db.Column(db.Integer)
    premio_usd = db.Column(db.Float, nullable=False)
    creditos_acumulados = db.Column(db.Integer, nullable=False)
    fecha_pago = db.Column(db.DateTime, default=datetime.utcnow)
    
    agencia = db.relationship('Agencia', backref='gastos_premios')
    perfil = db.relationship('Perfil', backref='premios_ganados')

class Perfil(db.Model):
    __tablename__ = 'perfil'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(20), unique=True, nullable=True)
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
    tier = db.Column(db.String(20), default='Standard')
    fotos = db.relationship('Foto', backref='perfil', lazy=True, cascade='all, delete-orphan')
    
    def generate_public_id(self):
        ultimo = Perfil.query.filter(Perfil.public_id.isnot(None)).order_by(Perfil.id.desc()).first()
        if ultimo and ultimo.public_id:
            try:
                num = int(ultimo.public_id[1:]) + 1
                return f"P{num}"
            except:
                pass
        return "P2001"

class Cliente(db.Model):
    __tablename__ = 'cliente'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(20), unique=True, nullable=True)
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
    
    def generate_public_id(self):
        ultimo = Cliente.query.filter(Cliente.public_id.isnot(None)).order_by(Cliente.id.desc()).first()
        if ultimo and ultimo.public_id:
            try:
                num = int(ultimo.public_id[1:]) + 1
                return f"V{num}"
            except:
                pass
        return "V3001"

class Mensaje(db.Model):
    __tablename__ = 'mensaje'
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
    es_regalo = db.Column(db.Boolean, default=False)
    regalo_id = db.Column(db.Integer, db.ForeignKey('regalo.id'), nullable=True)

class Favorito(db.Model):
    __tablename__ = 'favorito'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'))
    perfil_id = db.Column(db.Integer, db.ForeignKey('perfil.id'))
    es_match = db.Column(db.Boolean, default=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    perfil = db.relationship('Perfil', backref='favoritos_recibidos')

class Foto(db.Model):
    __tablename__ = 'foto'
    id = db.Column(db.Integer, primary_key=True)
    perfil_id = db.Column(db.Integer, db.ForeignKey('perfil.id'))
    ruta = db.Column(db.String(200), nullable=False)
    es_privada = db.Column(db.Boolean, default=False)
    costo = db.Column(db.Integer, default=10)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)

class FotoComprada(db.Model):
    __tablename__ = 'foto_comprada'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'))
    foto_id = db.Column(db.Integer, db.ForeignKey('foto.id'))
    fecha_compra = db.Column(db.DateTime, default=datetime.utcnow)

class ClienteFoto(db.Model):
    __tablename__ = 'cliente_foto'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'))
    ruta = db.Column(db.String(200), nullable=False)
    es_principal = db.Column(db.Boolean, default=False)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)

class Rate(db.Model):
    __tablename__ = 'rate'
    id = db.Column(db.Integer, primary_key=True)
    accion = db.Column(db.String(50), unique=True)
    creditos_costo = db.Column(db.Integer, default=1)
    creditos_ganancia_modelo = db.Column(db.Integer, default=1)
    valor_usd = db.Column(db.Float, default=0.10)
    activo = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class LogConexion(db.Model):
    __tablename__ = 'log_conexion'
    id = db.Column(db.Integer, primary_key=True)
    perfil_id = db.Column(db.Integer, db.ForeignKey('perfil.id'))
    tipo = db.Column(db.String(20))
    ip = db.Column(db.String(50))
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    perfil = db.relationship('Perfil', backref='logs_conexion')

# ============================
# FUNCIONES AUXILIARES
# ============================
def registrar_log_admin(accion, detalles=None, admin_id=None, admin_nombre=None, admin_email=None, ip=None):
    try:
        if admin_id is None:
            admin_id = session.get('admin_id')
        if admin_nombre is None:
            admin_nombre = session.get('admin_nombre')
        if admin_email is None:
            admin_email = session.get('admin_email')
        if ip is None:
            ip = request.remote_addr
        
        log = LogAdmin(
            admin_id=admin_id,
            admin_nombre=admin_nombre,
            admin_email=admin_email,
            accion=accion,
            detalles=json.dumps(detalles) if detalles else None,
            ip=ip
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"Error al registrar log: {e}")
        db.session.rollback()

def registrar_login_fallido(email, ip=None):
    try:
        if ip is None:
            ip = request.remote_addr
        log = LogLoginFallido(email_intentado=email, ip=ip)
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"Error al registrar login fallido: {e}")
        db.session.rollback()

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

def obtener_valor_credito():
    return float(ConfigGlobal.get('valor_credito_usd', '0.10'))

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

# ============================
# RUTAS DE AUTENTICACIÓN
# ============================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/leaderboard-popup')
def leaderboard_popup():
    return render_template('leaderboard_popup.html')

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
    db.session.flush()
    nuevo_cliente.public_id = nuevo_cliente.generate_public_id()
    db.session.commit()
    
    session['user_id'] = nuevo_cliente.id
    session['tipo'] = 'cliente'
    session.permanent = True
    return jsonify({'success': True, 'redirect': '/app', 'public_id': nuevo_cliente.public_id})

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    ip = request.remote_addr
    
    admin = Admin.query.filter_by(email=email).first()
    if admin and check_password_hash(admin.password_hash, password):
        session['tipo'] = 'supervisor'
        session['admin_id'] = admin.id
        session['admin_nombre'] = admin.nombre
        session['admin_email'] = admin.email
        session.permanent = True
        registrar_log_admin('LOGIN_ADMIN', detalles={'email': email}, admin_id=admin.id, admin_nombre=admin.nombre, admin_email=admin.email, ip=ip)
        return jsonify({'redirect': '/master'})
    
    cliente = Cliente.query.filter_by(correo=email).first()
    if cliente and check_password_hash(cliente.password_hash, password):
        session['user_id'] = cliente.id
        session['tipo'] = 'cliente'
        session.permanent = True
        return jsonify({'redirect': f'/app?visitor={cliente.public_id}'})
    
    perfil = Perfil.query.filter_by(correo=email).first()
    if perfil and check_password_hash(perfil.password_hash, password):
        session['perfil_id'] = perfil.id
        session['tipo'] = 'modelo'
        session.permanent = True
        perfil.is_online = True
        perfil.ultima_conexion = datetime.utcnow()
        perfil.ultima_ip = ip
        registrar_log_conexion(perfil.id, 'login', ip)
        db.session.commit()
        return jsonify({'redirect': f'/people/{perfil.public_id}'})
    
    agencia = Agencia.query.filter_by(correo=email).first()
    if agencia and check_password_hash(agencia.password_hash, password):
        session['agencia_id'] = agencia.id
        session['tipo'] = 'agencia'
        session.permanent = True
        return jsonify({'redirect': f'/agency/panel'})
    
    registrar_login_fallido(email, ip)
    return jsonify({'msg': 'Credenciales incorrectas'}), 401

@app.route('/logout')
def logout():
    if session.get('tipo') == 'supervisor':
        registrar_log_admin('LOGOUT_ADMIN', detalles={'email': session.get('admin_email')})
    elif session.get('tipo') == 'modelo' and session.get('perfil_id'):
        perfil = Perfil.query.get(session['perfil_id'])
        if perfil:
            perfil.is_online = False
            registrar_log_conexion(perfil.id, 'logout', request.remote_addr)
            db.session.commit()
    session.clear()
    return redirect('/')

# ============================
# RUTAS SUPERADMIN
# ============================
@app.route('/master')
@superadmin_required
def master():
    return render_template('supervisor.html')

@app.route('/master/regalos')
@superadmin_required
def master_regalos():
    return render_template('superadmin_regalos.html')

@app.route('/api/superadmin/me', methods=['GET'])
@superadmin_required
def api_superadmin_me():
    admin_id = session.get('admin_id')
    admin_nombre = session.get('admin_nombre')
    admin_email = session.get('admin_email')
    
    if admin_id and admin_nombre and admin_email:
        return jsonify({'id': admin_id, 'nombre': admin_nombre, 'email': admin_email})
    
    admin = Admin.query.get(admin_id) if admin_id else None
    if admin:
        return jsonify({'id': admin.id, 'nombre': admin.nombre, 'email': admin.email})
    
    return jsonify({'error': 'No se encontró el administrador'}), 404

# ========== CONFIGURACIÓN GLOBAL ==========
@app.route('/api/superadmin/config', methods=['GET'])
@superadmin_required
def api_get_config():
    configs = ConfigGlobal.query.all()
    return jsonify({c.clave: c.valor for c in configs})

@app.route('/api/superadmin/config/actualizar', methods=['POST'])
@superadmin_required
def api_actualizar_config():
    data = request.get_json()
    cambios = {}
    for clave, valor in data.items():
        viejo = ConfigGlobal.get(clave)
        if viejo != str(valor):
            cambios[clave] = {'anterior': viejo, 'nuevo': valor}
        ConfigGlobal.set(clave, str(valor))
    
    if cambios:
        registrar_log_admin('ACTUALIZAR_CONFIG_GLOBAL', detalles=cambios)
    return jsonify({'success': True})

# ========== REGALOS ==========
@app.route('/api/superadmin/regalos', methods=['GET'])
@superadmin_required
def api_get_regalos():
    regalos = Regalo.query.order_by(Regalo.orden).all()
    return jsonify([r.to_dict() for r in regalos])

@app.route('/api/superadmin/regalo/crear', methods=['POST'])
@superadmin_required
def api_crear_regalo():
    data = request.get_json()
    nuevo = Regalo(
        nombre=data.get('nombre'),
        emoji=data.get('emoji'),
        costo_creditos=int(data.get('costo_creditos', 10)),
        orden=int(data.get('orden', 999)),
        activo=data.get('activo', True)
    )
    db.session.add(nuevo)
    db.session.commit()
    registrar_log_admin('CREAR_REGALO', detalles={'nombre': nuevo.nombre, 'costo': nuevo.costo_creditos})
    return jsonify({'success': True, 'id': nuevo.id})

@app.route('/api/superadmin/regalo/<int:regalo_id>/editar', methods=['PUT'])
@superadmin_required
def api_editar_regalo(regalo_id):
    regalo = Regalo.query.get_or_404(regalo_id)
    data = request.get_json()
    
    cambios = {}
    if data.get('nombre') and data.get('nombre') != regalo.nombre:
        cambios['nombre_anterior'] = regalo.nombre
        cambios['nombre_nuevo'] = data.get('nombre')
        regalo.nombre = data.get('nombre')
    if data.get('emoji') and data.get('emoji') != regalo.emoji:
        cambios['emoji_anterior'] = regalo.emoji
        cambios['emoji_nuevo'] = data.get('emoji')
        regalo.emoji = data.get('emoji')
    if data.get('costo_creditos'):
        cambios['costo_anterior'] = regalo.costo_creditos
        cambios['costo_nuevo'] = int(data.get('costo_creditos'))
        regalo.costo_creditos = int(data.get('costo_creditos'))
    if data.get('orden'):
        regalo.orden = int(data.get('orden'))
    if 'activo' in data:
        regalo.activo = data.get('activo')
    
    db.session.commit()
    if cambios:
        registrar_log_admin('EDITAR_REGALO', detalles={'regalo_id': regalo.id, 'cambios': cambios})
    return jsonify({'success': True})

@app.route('/api/superadmin/regalo/<int:regalo_id>/eliminar', methods=['DELETE'])
@superadmin_required
def api_eliminar_regalo(regalo_id):
    regalo = Regalo.query.get_or_404(regalo_id)
    registrar_log_admin('ELIMINAR_REGALO', detalles={'nombre': regalo.nombre, 'id': regalo.id})
    db.session.delete(regalo)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/regalos/activos', methods=['GET'])
@login_required
def api_get_regalos_activos():
    regalos = Regalo.query.filter_by(activo=True).order_by(Regalo.costo_creditos).all()
    return jsonify([r.to_dict() for r in regalos])

# ========== LOGS / AUDITORÍA ==========
@app.route('/api/superadmin/logs', methods=['GET'])
@superadmin_required
def api_superadmin_logs():
    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')
    admin_id = request.args.get('admin_id')
    accion = request.args.get('accion')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    
    query = LogAdmin.query
    
    if fecha_desde:
        try:
            fecha_desde_dt = datetime.strptime(fecha_desde, '%Y-%m-%d')
            query = query.filter(LogAdmin.fecha >= fecha_desde_dt)
        except:
            pass
    if fecha_hasta:
        try:
            fecha_hasta_dt = datetime.strptime(fecha_hasta, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(LogAdmin.fecha <= fecha_hasta_dt)
        except:
            pass
    if admin_id and admin_id != 'todos':
        query = query.filter(LogAdmin.admin_id == int(admin_id))
    if accion and accion != 'todas':
        query = query.filter(LogAdmin.accion == accion)
    
    paginated = query.order_by(LogAdmin.fecha.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'logs': [{
            'id': l.id,
            'admin_nombre': l.admin_nombre,
            'admin_email': l.admin_email,
            'accion': l.accion,
            'detalles': json.loads(l.detalles) if l.detalles else None,
            'ip': l.ip,
            'fecha': l.fecha.strftime('%Y-%m-%d %H:%M:%S') if l.fecha else ''
        } for l in paginated.items],
        'total': paginated.total,
        'page': page,
        'per_page': per_page,
        'pages': paginated.pages
    })

@app.route('/api/superadmin/logs/export', methods=['GET'])
@superadmin_required
def api_superadmin_logs_export():
    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')
    admin_id = request.args.get('admin_id')
    accion = request.args.get('accion')
    
    query = LogAdmin.query
    if fecha_desde:
        try:
            fecha_desde_dt = datetime.strptime(fecha_desde, '%Y-%m-%d')
            query = query.filter(LogAdmin.fecha >= fecha_desde_dt)
        except:
            pass
    if fecha_hasta:
        try:
            fecha_hasta_dt = datetime.strptime(fecha_hasta, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(LogAdmin.fecha <= fecha_hasta_dt)
        except:
            pass
    if admin_id and admin_id != 'todos':
        query = query.filter(LogAdmin.admin_id == int(admin_id))
    if accion and accion != 'todas':
        query = query.filter(LogAdmin.accion == accion)
    
    logs = query.order_by(LogAdmin.fecha.desc()).all()
    
    import csv
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Admin', 'Email', 'Acción', 'Detalles', 'IP', 'Fecha'])
    for l in logs:
        writer.writerow([l.id, l.admin_nombre or '', l.admin_email or '', l.accion, l.detalles or '', l.ip or '', l.fecha.strftime('%Y-%m-%d %H:%M:%S') if l.fecha else ''])
    output.seek(0)
    return output.getvalue(), 200, {'Content-Type': 'text/csv', 'Content-Disposition': f'attachment; filename=logs_admin_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'}

@app.route('/api/superadmin/login-failed-logs', methods=['GET'])
@superadmin_required
def api_superadmin_login_failed_logs():
    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    
    query = LogLoginFallido.query
    if fecha_desde:
        try:
            fecha_desde_dt = datetime.strptime(fecha_desde, '%Y-%m-%d')
            query = query.filter(LogLoginFallido.fecha >= fecha_desde_dt)
        except:
            pass
    if fecha_hasta:
        try:
            fecha_hasta_dt = datetime.strptime(fecha_hasta, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(LogLoginFallido.fecha <= fecha_hasta_dt)
        except:
            pass
    
    paginated = query.order_by(LogLoginFallido.fecha.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'logs': [{'id': l.id, 'email_intentado': l.email_intentado, 'ip': l.ip, 'fecha': l.fecha.strftime('%Y-%m-%d %H:%M:%S') if l.fecha else ''} for l in paginated.items],
        'total': paginated.total, 'page': page, 'per_page': per_page, 'pages': paginated.pages
    })

@app.route('/api/superadmin/acciones-lista', methods=['GET'])
@superadmin_required
def api_superadmin_acciones_lista():
    acciones = ['LOGIN_ADMIN', 'LOGOUT_ADMIN', 'CREAR_ADMIN', 'EDITAR_ADMIN', 'ELIMINAR_ADMIN', 'RESET_PASS_ADMIN', 'CREAR_AGENCIA', 'EDITAR_AGENCIA', 'ELIMINAR_AGENCIA', 'CREAR_MODELO', 'EDITAR_MODELO', 'ELIMINAR_MODELO', 'CREAR_REGALO', 'EDITAR_REGALO', 'ELIMINAR_REGALO', 'ACTUALIZAR_CONFIG_GLOBAL', 'ACTUALIZAR_BONOS_AGENCIA']
    return jsonify({'acciones': acciones})

# ========== ADMINISTRADORES ==========
@app.route('/api/superadmin/admins', methods=['GET'])
@superadmin_required
def api_superadmin_admins():
    admins = Admin.query.all()
    return jsonify([{'id': a.id, 'nombre': a.nombre, 'email': a.email, 'created_at': a.created_at.strftime('%Y-%m-%d') if a.created_at else ''} for a in admins])

@app.route('/api/superadmin/admin/create', methods=['POST'])
@superadmin_required
def api_superadmin_admin_create():
    data = request.get_json()
    if Admin.query.filter_by(email=data.get('email')).first():
        return jsonify({'success': False, 'msg': 'El email ya existe'}), 400
    nuevo = Admin(nombre=data.get('nombre', 'Admin'), email=data.get('email'), password_hash=generate_password_hash(data.get('password', 'admin123')))
    db.session.add(nuevo)
    db.session.commit()
    registrar_log_admin('CREAR_ADMIN', detalles={'nombre': nuevo.nombre, 'email': nuevo.email, 'id': nuevo.id})
    return jsonify({'success': True, 'id': nuevo.id})

@app.route('/api/superadmin/admin/<int:admin_id>/reset', methods=['POST'])
@superadmin_required
def api_superadmin_admin_reset(admin_id):
    admin = Admin.query.get_or_404(admin_id)
    data = request.get_json()
    admin.password_hash = generate_password_hash(data.get('password'))
    db.session.commit()
    registrar_log_admin('RESET_PASS_ADMIN', detalles={'admin_id': admin_id, 'email': admin.email})
    return jsonify({'success': True})

@app.route('/api/superadmin/admin/<int:admin_id>/update', methods=['PUT'])
@superadmin_required
def api_superadmin_admin_update(admin_id):
    admin = Admin.query.get_or_404(admin_id)
    data = request.get_json()
    cambios = {}
    if data.get('nombre') and data.get('nombre') != admin.nombre:
        cambios['nombre_anterior'] = admin.nombre
        cambios['nombre_nuevo'] = data.get('nombre')
        admin.nombre = data.get('nombre')
    if data.get('email') and data.get('email') != admin.email:
        cambios['email_anterior'] = admin.email
        cambios['email_nuevo'] = data.get('email')
        admin.email = data.get('email')
    db.session.commit()
    if cambios:
        registrar_log_admin('EDITAR_ADMIN', detalles={'admin_id': admin_id, 'cambios': cambios})
    return jsonify({'success': True})

@app.route('/api/superadmin/admin/<int:admin_id>/delete', methods=['DELETE'])
@superadmin_required
def api_superadmin_admin_delete(admin_id):
    admin = Admin.query.get_or_404(admin_id)
    registrar_log_admin('ELIMINAR_ADMIN', detalles={'admin_id': admin.id, 'nombre': admin.nombre, 'email': admin.email})
    db.session.delete(admin)
    db.session.commit()
    return jsonify({'success': True})

# ========== AGENCIAS ==========
@app.route('/api/crear_agencia', methods=['POST'])
@superadmin_required
def api_crear_agencia():
    try:
        data = request.get_json()
        if Agencia.query.filter_by(correo=data['correo']).first():
            return jsonify({'success': False, 'msg': 'El correo ya existe'}), 400
        
        nueva = Agencia(
            nombre=data['nombre'],
            correo=data['correo'],
            password_hash=generate_password_hash(data['password']),
            comision_agencia=int(data.get('comision_agencia', 25)),
            comision_plataforma=int(data.get('comision_plataforma', 60)),
            comision_modelo=int(data.get('comision_modelo', 15)),
            pais=data.get('pais', 'Colombia')
        )
        db.session.add(nueva)
        db.session.flush()
        nueva.public_id = nueva.generate_public_id()
        
        bono_config = AgenciaBono(agencia_id=nueva.id)
        db.session.add(bono_config)
        
        premio_config = PremioLeaderboard(agencia_id=nueva.id)
        db.session.add(premio_config)
        db.session.commit()
        
        registrar_log_admin('CREAR_AGENCIA', detalles={'public_id': nueva.public_id, 'nombre': nueva.nombre, 'email': nueva.correo, 'comisiones': {'plataforma': nueva.comision_plataforma, 'agencia': nueva.comision_agencia, 'modelo': nueva.comision_modelo}})
        return jsonify({'success': True, 'public_id': nueva.public_id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'msg': str(e)}), 500

@app.route('/api/eliminar_agencia/<string:public_id>', methods=['DELETE'])
@superadmin_required
def api_eliminar_agencia(public_id):
    agencia = Agencia.query.filter_by(public_id=public_id).first_or_404()
    registrar_log_admin('ELIMINAR_AGENCIA', detalles={'public_id': agencia.public_id, 'nombre': agencia.nombre, 'email': agencia.correo})
    db.session.delete(agencia)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/superadmin/agencies', methods=['GET'])
@superadmin_required
def api_superadmin_agencies():
    agencias = Agencia.query.all()
    result = []
    for a in agencias:
        total_creditos = sum(p.creditos_generados for p in a.perfiles)
        result.append({
            'public_id': a.public_id,
            'name': a.nombre,
            'email': a.correo,
            'country': a.pais,
            'comision_plataforma': a.comision_plataforma,
            'comision_agencia': a.comision_agencia,
            'comision_modelo': a.comision_modelo,
            'models': len(a.perfiles),
            'earnings': total_creditos * 0.10,
            'joined': a.created_at.strftime('%Y-%m-%d') if a.created_at else ''
        })
    return jsonify(result)

@app.route('/api/superadmin/agency/<string:public_id>/update', methods=['PUT'])
@superadmin_required
def api_superadmin_agency_update(public_id):
    agencia = Agencia.query.filter_by(public_id=public_id).first_or_404()
    data = request.get_json()
    cambios = {}
    
    if data.get('name') and data.get('name') != agencia.nombre:
        cambios['nombre_anterior'] = agencia.nombre
        cambios['nombre_nuevo'] = data.get('name')
        agencia.nombre = data.get('name')
    if data.get('email') and data.get('email') != agencia.correo:
        cambios['email_anterior'] = agencia.correo
        cambios['email_nuevo'] = data.get('email')
        agencia.correo = data.get('email')
    if data.get('country') and data.get('country') != agencia.pais:
        cambios['pais_anterior'] = agencia.pais
        cambios['pais_nuevo'] = data.get('country')
        agencia.pais = data.get('country')
    if data.get('comision_plataforma'):
        cambios['comision_plataforma_anterior'] = agencia.comision_plataforma
        cambios['comision_plataforma_nuevo'] = int(data.get('comision_plataforma'))
        agencia.comision_plataforma = int(data.get('comision_plataforma'))
    if data.get('comision_agencia'):
        cambios['comision_agencia_anterior'] = agencia.comision_agencia
        cambios['comision_agencia_nuevo'] = int(data.get('comision_agencia'))
        agencia.comision_agencia = int(data.get('comision_agencia'))
    if data.get('comision_modelo'):
        cambios['comision_modelo_anterior'] = agencia.comision_modelo
        cambios['comision_modelo_nuevo'] = int(data.get('comision_modelo'))
        agencia.comision_modelo = int(data.get('comision_modelo'))
    
    db.session.commit()
    if cambios:
        registrar_log_admin('EDITAR_AGENCIA', detalles={'public_id': agencia.public_id, 'cambios': cambios})
    return jsonify({'success': True})

# ========== MODELOS ==========
@app.route('/api/crear_perfil', methods=['POST'])
@superadmin_required
def api_crear_perfil():
    try:
        nombre = request.form.get('nombre')
        correo = request.form.get('correo')
        password = request.form.get('password')
        agencia_public_id = request.form.get('agencia_id')
        pais = request.form.get('pais', 'Colombia')
        tier = request.form.get('tier', 'Standard')
        
        if not nombre or not correo or not agencia_public_id:
            return jsonify({'success': False, 'msg': 'Faltan campos requeridos'}), 400
        
        agencia = Agencia.query.filter_by(public_id=agencia_public_id).first()
        if not agencia:
            return jsonify({'success': False, 'msg': 'La agencia no existe'}), 400
        
        if Perfil.query.filter_by(correo=correo).first():
            return jsonify({'success': False, 'msg': 'El correo ya existe'}), 400
            
        foto_filename = 'default_user.png'
        if 'foto' in request.files:
            file = request.files['foto']
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[-1].lower()
                foto_filename = secure_filename(f"perfil_{uuid.uuid4().hex[:8]}.{ext}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_filename))
        
        nuevo = Perfil(
            nombre=nombre,
            correo=correo,
            password_hash=generate_password_hash(password),
            agencia_id=agencia.id,
            foto_principal=foto_filename,
            foto_portada=foto_filename,
            pais=pais,
            tier=tier,
            is_online=False,
            verificado=False
        )
        db.session.add(nuevo)
        db.session.flush()
        nuevo.public_id = nuevo.generate_public_id()
        db.session.commit()
        
        registrar_log_admin('CREAR_MODELO', detalles={'public_id': nuevo.public_id, 'nombre': nuevo.nombre, 'email': nuevo.correo, 'agencia_id': agencia_public_id, 'tier': tier})
        return jsonify({'success': True, 'public_id': nuevo.public_id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'msg': str(e)}), 500

@app.route('/api/eliminar_perfil/<string:public_id>', methods=['DELETE'])
@superadmin_required
def api_eliminar_perfil(public_id):
    perfil = Perfil.query.filter_by(public_id=public_id).first_or_404()
    registrar_log_admin('ELIMINAR_MODELO', detalles={'public_id': perfil.public_id, 'nombre': perfil.nombre, 'email': perfil.correo})
    db.session.delete(perfil)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/superadmin/models', methods=['GET'])
@superadmin_required
def api_superadmin_models():
    perfiles = Perfil.query.all()
    result = []
    for p in perfiles:
        result.append({
            'public_id': p.public_id,
            'name': p.nombre,
            'email': p.correo,
            'agency_name': p.agencia.nombre if p.agencia else 'Sin agencia',
            'tier': p.tier,
            'status': 'active' if p.is_online else 'inactive',
            'online': p.is_online,
            'creditos_generados': p.creditos_generados,
            'earnings': p.creditos_generados * 0.10,
            'photo': p.foto_principal
        })
    return jsonify(result)

@app.route('/api/superadmin/model/<string:public_id>/update', methods=['PUT'])
@superadmin_required
def api_superadmin_model_update(public_id):
    perfil = Perfil.query.filter_by(public_id=public_id).first_or_404()
    data = request.get_json()
    cambios = {}
    
    if data.get('alias') and data.get('alias') != perfil.nombre:
        cambios['nombre_anterior'] = perfil.nombre
        cambios['nombre_nuevo'] = data.get('alias')
        perfil.nombre = data.get('alias')
    if data.get('email') and data.get('email') != perfil.correo:
        cambios['email_anterior'] = perfil.correo
        cambios['email_nuevo'] = data.get('email')
        perfil.correo = data.get('email')
    if data.get('tier') and data.get('tier') != perfil.tier:
        cambios['tier_anterior'] = perfil.tier
        cambios['tier_nuevo'] = data.get('tier')
        perfil.tier = data.get('tier')
    if data.get('agency_public_id'):
        agencia = Agencia.query.filter_by(public_id=data.get('agency_public_id')).first()
        if agencia and agencia.id != perfil.agencia_id:
            cambios['agencia_anterior_id'] = perfil.agencia_id
            cambios['agencia_nueva_id'] = agencia.public_id
            perfil.agencia_id = agencia.id
    if data.get('status'):
        nuevo_status = data.get('status') == 'active'
        if nuevo_status != perfil.is_online:
            cambios['status_anterior'] = perfil.is_online
            cambios['status_nuevo'] = nuevo_status
            perfil.is_online = nuevo_status
    
    db.session.commit()
    if cambios:
        registrar_log_admin('EDITAR_MODELO', detalles={'public_id': perfil.public_id, 'cambios': cambios})
    return jsonify({'success': True})

# ========== ESTADÍSTICAS ==========
@app.route('/api/superadmin/statistics', methods=['GET'])
@superadmin_required
def api_superadmin_statistics():
    agencias = Agencia.query.all()
    perfiles = Perfil.query.all()
    creditos_totales = sum(p.creditos_generados for p in perfiles)
    
    return jsonify({
        'total_agencias': len(agencias),
        'total_modelos': len(perfiles),
        'modelos_online': sum(1 for p in perfiles if p.is_online),
        'ganancias_totales': creditos_totales * 0.10,
        'promociones_activas': 0,
        'penalizaciones_activas': 0
    })

@app.route('/api/superadmin/activities', methods=['GET'])
@superadmin_required
def api_superadmin_activities():
    logs = LogConexion.query.order_by(LogConexion.fecha.desc()).limit(10).all()
    result = []
    for log in logs:
        perfil = Perfil.query.get(log.perfil_id)
        if perfil:
            result.append({'ico': '👩', 'bg': 'rgba(236,72,153,.1)', 'color': '#ec4899', 'text': f'{perfil.nombre} - {log.tipo}', 'time': log.fecha.strftime('%H:%M') if log.fecha else 'Recientemente'})
    return jsonify(result)

@app.route('/api/superadmin/search', methods=['GET'])
@superadmin_required
def api_superadmin_search():
    query = request.args.get('q', '').strip()
    results = []
    if query:
        agencias = Agencia.query.filter(db.or_(Agencia.nombre.ilike(f'%{query}%'), Agencia.correo.ilike(f'%{query}%'))).limit(5).all()
        for a in agencias:
            results.append({'type': 'agency', 'public_id': a.public_id, 'name': a.nombre, 'email': a.correo, 'status': 'active'})
        perfiles = Perfil.query.filter(db.or_(Perfil.nombre.ilike(f'%{query}%'), Perfil.correo.ilike(f'%{query}%'))).limit(5).all()
        for p in perfiles:
            results.append({'type': 'model', 'public_id': p.public_id, 'name': p.nombre, 'email': p.correo, 'agency_name': p.agencia.nombre if p.agencia else 'Sin agencia'})
    return jsonify({'results': results})

# ========== RUTAS DE AGENCIA ==========
@app.route('/agency/panel')
@agencia_required
def agency_panel():
    agencia = Agencia.query.get(session.get('agencia_id'))
    if not agencia:
        abort(404)
    
    perfiles = Perfil.query.filter_by(agencia_id=agencia.id).all()
    ahora = datetime.utcnow()
    hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    hace_30_min = ahora - timedelta(minutes=30)
    
    modelos_online = sum(1 for p in perfiles if p.is_online)
    total_modelos = len(perfiles)
    
    conexiones_activas = LogConexion.query.filter(
        LogConexion.perfil_id.in_([p.id for p in perfiles]),
        LogConexion.fecha >= hace_30_min,
        LogConexion.tipo == 'login'
    ).count()
    
    creditos_hoy = 0
    creditos_totales = 0
    for perfil in perfiles:
        msgs_hoy = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= hoy
        ).all()
        creditos_hoy += sum(m.creditos_generados for m in msgs_hoy)
        creditos_totales += perfil.creditos_generados
    
    ingresos_hoy = creditos_hoy * 0.10
    ingreso_neto = ingresos_hoy * agencia.comision_agencia / 100
    
    horas_data = []
    for i in range(24):
        hora_inicio = hoy.replace(hour=i)
        hora_fin = hora_inicio + timedelta(hours=1)
        creditos_hora = 0
        for perfil in perfiles:
            msgs_hora = Mensaje.query.filter(
                (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
                Mensaje.fecha >= hora_inicio,
                Mensaje.fecha < hora_fin
            ).all()
            creditos_hora += sum(m.creditos_generados for m in msgs_hora)
        horas_data.append(creditos_hora)
    
    top_modelos = []
    for perfil in perfiles:
        msgs_hoy = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= hoy
        ).all()
        creditos_perfil_hoy = sum(m.creditos_generados for m in msgs_hoy)
        regalos_hoy = sum(1 for m in msgs_hoy if m.es_regalo)
        tier = perfil.tier or 'Standard'
        meta_diaria = 1000 if tier == 'VIP' else 800 if tier == 'Premium' else 600
        completado = round((creditos_perfil_hoy / meta_diaria) * 100, 1) if creditos_perfil_hoy > 0 else 0
        
        top_modelos.append({
            'public_id': perfil.public_id,
            'nombre': perfil.nombre,
            'creditos_hoy': creditos_perfil_hoy,
            'creditos_totales': perfil.creditos_generados,
            'is_online': perfil.is_online,
            'tier': tier,
            'foto': perfil.foto_principal,
            'mensajes': len(msgs_hoy),
            'regalos': regalos_hoy,
            'meta_diaria': meta_diaria,
            'completado': completado,
            'pais': perfil.pais or 'No especificado',
            'ip': perfil.ultima_ip or '192.168.1.1'
        })
    top_modelos.sort(key=lambda x: x['creditos_hoy'], reverse=True)
    
    alertas_vivo = []
    hace_1_hora = ahora - timedelta(hours=1)
    for perfil in perfiles:
        mensajes_recientes = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= hace_1_hora
        ).order_by(Mensaje.fecha.desc()).limit(10).all()
        for m in mensajes_recientes:
            if m.es_regalo:
                minutos = int((ahora - m.fecha).total_seconds() / 60)
                alertas_vivo.append({'tipo': 'gift', 'mensaje': f'🎁 Regalo recibido', 'tiempo': f'hace {minutos} min' if minutos > 0 else 'hace unos segundos'})
    
    earnings_data = []
    for perfil in perfiles[:7]:
        creditos_por_hora = []
        for i in range(8, 23):
            hora_inicio = hoy.replace(hour=i)
            hora_fin = hora_inicio + timedelta(hours=1)
            msgs_hora = Mensaje.query.filter(
                (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
                Mensaje.fecha >= hora_inicio,
                Mensaje.fecha < hora_fin
            ).all()
            creditos_por_hora.append(sum(m.creditos_generados for m in msgs_hora))
        earnings_data.append({'public_id': perfil.public_id, 'nombre': perfil.nombre, 'datos': creditos_por_hora, 'total': sum(creditos_por_hora)})
    
    transacciones = []
    for perfil in perfiles:
        mensajes = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id)
        ).order_by(Mensaje.fecha.desc()).limit(50).all()
        for m in mensajes[:20]:
            if m.emisor_cliente_id:
                cliente = Cliente.query.get(m.emisor_cliente_id)
                if cliente:
                    transacciones.append({
                        'id': f'TXN-{m.id}',
                        'fecha': m.fecha.strftime('%d/%m/%Y'),
                        'hora': m.fecha.strftime('%H:%M'),
                        'cliente_nombre': cliente.nombre_real,
                        'cliente_id': cliente.public_id,
                        'regalo': 'Regalo' if m.es_regalo else 'Mensaje',
                        'modelo_nombre': perfil.nombre,
                        'creditos': m.creditos_generados,
                        'usd': m.creditos_generados * 0.10,
                        'comision_agencia': m.creditos_generados * 0.10 * agencia.comision_agencia / 100
                    })
    transacciones = transacciones[:30]
    
    fecha_lunes = ahora - timedelta(days=ahora.weekday())
    dia_del_ano = ahora.timetuple().tm_yday
    semana_numero = ((dia_del_ano - ahora.weekday() + 6) // 7) + 1
    
    fechas_semana = []
    for i in range(7):
        fecha = fecha_lunes + timedelta(days=i)
        fechas_semana.append({
            'nombre': ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'][i],
            'dia': fecha.strftime('%d'),
            'activos': modelos_online
        })
    
    parametros = {
        'valor_credito_usd': 0.10,
        'comision_plataforma': agencia.comision_plataforma,
        'comision_agencia': agencia.comision_agencia,
        'comision_modelo': agencia.comision_modelo,
        'comision_vip': 30,
        'comision_premium': 35,
        'comision_standard': 40,
        'meta_vip': 1000,
        'meta_premium': 800,
        'meta_standard': 600
    }
    
    vip_clientes = []
    for perfil in perfiles:
        favoritos = Favorito.query.filter_by(perfil_id=perfil.id).all()
        for fav in favoritos[:5]:
            cliente = Cliente.query.get(fav.cliente_id)
            if cliente and cliente.creditos > 500:
                vip_clientes.append({
                    'public_id': cliente.public_id,
                    'nombre': cliente.nombre_real,
                    'username': cliente.correo.split('@')[0],
                    'pais': cliente.pais,
                    'creditos_gastados': 50000 - cliente.creditos,
                    'sesiones': 50,
                    'avg_por_sesion': 1000,
                    'is_online': True
                })
    vip_clientes = vip_clientes[:10]
    
    return render_template('agency_panel.html', 
                         agencia=agencia,
                         ahora=ahora,
                         fecha_lunes=fecha_lunes,
                         semana_numero=semana_numero,
                         fechas_semana=fechas_semana,
                         modelos_online=modelos_online,
                         total_modelos=total_modelos,
                         conexiones_activas=conexiones_activas,
                         creditos_totales=creditos_totales,
                         creditos_hoy=creditos_hoy,
                         ingresos_hoy=ingresos_hoy,
                         ingreso_neto=ingreso_neto,
                         horas_data=horas_data,
                         top_modelos=top_modelos[:5],
                         todos_modelos=top_modelos,
                         alertas_vivo=alertas_vivo,
                         earnings_data=earnings_data,
                         vip_clientes=vip_clientes,
                         transacciones=transacciones,
                         parametros=parametros)

@app.route('/agency/api/stats')
@agencia_required
def agency_api_stats():
    agencia = Agencia.query.get(session.get('agencia_id'))
    perfiles = Perfil.query.filter_by(agencia_id=agencia.id).all()
    hoy = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    creditos_hoy = 0
    for perfil in perfiles:
        msgs_hoy = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= hoy
        ).all()
        creditos_hoy += sum(m.creditos_generados for m in msgs_hoy)
    horas_data = []
    for i in range(24):
        hora_inicio = hoy.replace(hour=i)
        hora_fin = hora_inicio + timedelta(hours=1)
        creditos_hora = 0
        for perfil in perfiles:
            msgs_hora = Mensaje.query.filter(
                (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
                Mensaje.fecha >= hora_inicio,
                Mensaje.fecha < hora_fin
            ).all()
            creditos_hora += sum(m.creditos_generados for m in msgs_hora)
        horas_data.append(creditos_hora)
    return jsonify({
        'modelos_online': sum(1 for p in perfiles if p.is_online),
        'conexiones_activas': 0,
        'creditos_hoy': creditos_hoy,
        'horas_data': horas_data
    })

@app.route('/agency/api/bono-config', methods=['GET'])
@agencia_required
def agency_get_bono_config():
    agencia_id = session.get('agencia_id')
    config = AgenciaBono.query.filter_by(agencia_id=agencia_id).first()
    if not config:
        config = AgenciaBono(agencia_id=agencia_id)
        db.session.add(config)
        db.session.commit()
    return jsonify({
        'bono_activo': config.bono_activo,
        'bono_porcentaje': config.bono_porcentaje,
        'meta_diaria_creditos': config.meta_diaria_creditos,
        'meta_diaria_usd': config.meta_diaria_usd,
        'leaderboard_activo': config.leaderboard_activo,
        'premio_primer_lugar': config.premio_primer_lugar,
        'premio_segundo_lugar': config.premio_segundo_lugar,
        'premio_tercer_lugar': config.premio_tercer_lugar
    })

@app.route('/agency/api/bono-config/actualizar', methods=['POST'])
@agencia_required
def agency_update_bono_config():
    agencia_id = session.get('agencia_id')
    config = AgenciaBono.query.filter_by(agencia_id=agencia_id).first()
    if not config:
        config = AgenciaBono(agencia_id=agencia_id)
        db.session.add(config)
    
    data = request.get_json()
    if 'bono_activo' in data:
        config.bono_activo = data['bono_activo']
    if 'bono_porcentaje' in data:
        config.bono_porcentaje = int(data['bono_porcentaje'])
    if 'meta_diaria_creditos' in data:
        config.meta_diaria_creditos = int(data['meta_diaria_creditos'])
        config.meta_diaria_usd = config.meta_diaria_creditos * 0.10
    if 'leaderboard_activo' in data:
        config.leaderboard_activo = data['leaderboard_activo']
    if 'premio_primer_lugar' in data:
        config.premio_primer_lugar = int(data['premio_primer_lugar'])
    if 'premio_segundo_lugar' in data:
        config.premio_segundo_lugar = int(data['premio_segundo_lugar'])
    if 'premio_tercer_lugar' in data:
        config.premio_tercer_lugar = int(data['premio_tercer_lugar'])
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/agency/api/parametros', methods=['POST'])
@agencia_required
def agency_api_parametros():
    return jsonify({'success': True})

# ========== PREMIOS LEADERBOARD ==========
@app.route('/agency/api/premios-config', methods=['GET'])
@agencia_required
def agency_get_premios_config():
    agencia_id = session.get('agencia_id')
    config = PremioLeaderboard.query.filter_by(agencia_id=agencia_id).first()
    if not config:
        config = PremioLeaderboard(agencia_id=agencia_id)
        db.session.add(config)
        db.session.commit()
    
    return jsonify({
        'semanal_activo': config.semanal_activo,
        'semanal_premio1': config.semanal_premio1,
        'semanal_premio2': config.semanal_premio2,
        'semanal_premio3': config.semanal_premio3,
        'semanal_objetivo': config.semanal_objetivo,
        'quincenal_activo': config.quincenal_activo,
        'quincenal_premio1': config.quincenal_premio1,
        'quincenal_premio2': config.quincenal_premio2,
        'quincenal_premio3': config.quincenal_premio3,
        'quincenal_objetivo': config.quincenal_objetivo,
        'mensual_activo': config.mensual_activo,
        'mensual_premio1': config.mensual_premio1,
        'mensual_premio2': config.mensual_premio2,
        'mensual_premio3': config.mensual_premio3,
        'mensual_objetivo': config.mensual_objetivo,
    })

@app.route('/agency/api/premios-config/actualizar', methods=['POST'])
@agencia_required
def agency_update_premios_config():
    agencia_id = session.get('agencia_id')
    config = PremioLeaderboard.query.filter_by(agencia_id=agencia_id).first()
    if not config:
        config = PremioLeaderboard(agencia_id=agencia_id)
        db.session.add(config)
    
    data = request.get_json()
    # SEMANAL
    if 'semanal_activo' in data:
        config.semanal_activo = data['semanal_activo']
    if 'semanal_premio1' in data:
        config.semanal_premio1 = float(data['semanal_premio1'])
    if 'semanal_premio2' in data:
        config.semanal_premio2 = float(data['semanal_premio2'])
    if 'semanal_premio3' in data:
        config.semanal_premio3 = float(data['semanal_premio3'])
    if 'semanal_objetivo' in data:
        config.semanal_objetivo = int(data['semanal_objetivo'])
    
    # QUINCENAL
    if 'quincenal_activo' in data:
        config.quincenal_activo = data['quincenal_activo']
    if 'quincenal_premio1' in data:
        config.quincenal_premio1 = float(data['quincenal_premio1'])
    if 'quincenal_premio2' in data:
        config.quincenal_premio2 = float(data['quincenal_premio2'])
    if 'quincenal_premio3' in data:
        config.quincenal_premio3 = float(data['quincenal_premio3'])
    if 'quincenal_objetivo' in data:
        config.quincenal_objetivo = int(data['quincenal_objetivo'])
    
    # MENSUAL
    if 'mensual_activo' in data:
        config.mensual_activo = data['mensual_activo']
    if 'mensual_premio1' in data:
        config.mensual_premio1 = float(data['mensual_premio1'])
    if 'mensual_premio2' in data:
        config.mensual_premio2 = float(data['mensual_premio2'])
    if 'mensual_premio3' in data:
        config.mensual_premio3 = float(data['mensual_premio3'])
    if 'mensual_objetivo' in data:
        config.mensual_objetivo = int(data['mensual_objetivo'])
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/agency/api/leaderboard/hoy', methods=['GET'])
@agencia_required
def agency_get_leaderboard_hoy():
    agencia_id = session.get('agencia_id')
    hoy = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    perfiles = Perfil.query.filter_by(agencia_id=agencia_id).all()
    ranking = []
    for perfil in perfiles:
        mensajes = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= hoy
        ).all()
        creditos = sum(m.creditos_generados for m in mensajes)
        ranking.append({
            'perfil_id': perfil.id,
            'nombre': perfil.nombre,
            'foto': perfil.foto_principal,
            'creditos': creditos
        })
    
    ranking.sort(key=lambda x: x['creditos'], reverse=True)
    
    return jsonify({
        'ranking': ranking[:10],
        'premios': [],  # No premios para hoy
        'activo': False,  # No competencias diarias
        'objetivo': 0,
        'fecha_inicio': hoy.strftime('%Y-%m-%d %H:%M:%S'),
        'total_modelos': len(perfiles)
    })

@app.route('/agency/api/leaderboard/semanal', methods=['GET'])
@agencia_required
def agency_get_leaderboard_semanal():
    agencia_id = session.get('agencia_id')
    config = PremioLeaderboard.query.filter_by(agencia_id=agencia_id).first()
    
    if config and config.semanal_inicio_periodo:
        fecha_inicio = config.semanal_inicio_periodo
    else:
        hoy = datetime.utcnow()
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        fecha_inicio = inicio_semana.replace(hour=0, minute=0, second=0, microsecond=0)
    
    objetivo = config.semanal_objetivo if config else 0
    
    perfiles = Perfil.query.filter_by(agencia_id=agencia_id).all()
    ranking = []
    for perfil in perfiles:
        mensajes = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= fecha_inicio
        ).all()
        creditos = sum(m.creditos_generados for m in mensajes)
        if objetivo == 0 or creditos >= objetivo:
            ranking.append({
                'perfil_id': perfil.id,
                'nombre': perfil.nombre,
                'foto': perfil.foto_principal,
                'creditos': creditos
            })
    
    ranking.sort(key=lambda x: x['creditos'], reverse=True)
    
    premios = []
    if config and config.semanal_activo:
        premios = [config.semanal_premio1, config.semanal_premio2, config.semanal_premio3]
    
    return jsonify({
        'ranking': ranking[:10],
        'premios': premios,
        'activo': config.semanal_activo if config else True,
        'objetivo': objetivo,
        'fecha_inicio': fecha_inicio.strftime('%Y-%m-%d %H:%M:%S'),
        'total_modelos': len(perfiles)
    })

@app.route('/agency/api/leaderboard/quincenal', methods=['GET'])
@agencia_required
def agency_get_leaderboard_quincenal():
    agencia_id = session.get('agencia_id')
    config = PremioLeaderboard.query.filter_by(agencia_id=agencia_id).first()
    
    if config and config.quincenal_inicio_periodo:
        fecha_inicio = config.quincenal_inicio_periodo
    else:
        hoy = datetime.utcnow()
        if hoy.day < 16:
            fecha_inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            fecha_inicio = hoy.replace(day=16, hour=0, minute=0, second=0, microsecond=0)
    
    objetivo = config.quincenal_objetivo if config else 0
    
    perfiles = Perfil.query.filter_by(agencia_id=agencia_id).all()
    ranking = []
    for perfil in perfiles:
        mensajes = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= fecha_inicio
        ).all()
        creditos = sum(m.creditos_generados for m in mensajes)
        if objetivo == 0 or creditos >= objetivo:
            ranking.append({
                'perfil_id': perfil.id,
                'nombre': perfil.nombre,
                'foto': perfil.foto_principal,
                'creditos': creditos
            })
    
    ranking.sort(key=lambda x: x['creditos'], reverse=True)
    
    premios = []
    if config and config.quincenal_activo:
        premios = [config.quincenal_premio1, config.quincenal_premio2, config.quincenal_premio3]
    
    return jsonify({
        'ranking': ranking[:10],
        'premios': premios,
        'activo': config.quincenal_activo if config else False,
        'objetivo': objetivo,
        'fecha_inicio': fecha_inicio.strftime('%Y-%m-%d %H:%M:%S'),
        'total_modelos': len(perfiles)
    })

@app.route('/agency/api/leaderboard/mensual', methods=['GET'])
@agencia_required
def agency_get_leaderboard_mensual():
    agencia_id = session.get('agencia_id')
    config = PremioLeaderboard.query.filter_by(agencia_id=agencia_id).first()
    
    if config and config.mensual_inicio_periodo:
        fecha_inicio = config.mensual_inicio_periodo
    else:
        hoy = datetime.utcnow()
        fecha_inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    objetivo = config.mensual_objetivo if config else 0
    
    perfiles = Perfil.query.filter_by(agencia_id=agencia_id).all()
    ranking = []
    for perfil in perfiles:
        mensajes = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= fecha_inicio
        ).all()
        creditos = sum(m.creditos_generados for m in mensajes)
        if objetivo == 0 or creditos >= objetivo:
            ranking.append({
                'perfil_id': perfil.id,
                'nombre': perfil.nombre,
                'foto': perfil.foto_principal,
                'creditos': creditos
            })
    
    ranking.sort(key=lambda x: x['creditos'], reverse=True)
    
    premios = []
    if config and config.mensual_activo:
        premios = [config.mensual_premio1, config.mensual_premio2, config.mensual_premio3]
    
    return jsonify({
        'ranking': ranking[:10],
        'premios': premios,
        'activo': config.mensual_activo if config else True,
        'objetivo': objetivo,
        'fecha_inicio': fecha_inicio.strftime('%Y-%m-%d %H:%M:%S'),
        'total_modelos': len(perfiles)
    })

@app.route('/agency/api/leaderboard/cerrar-semanal', methods=['POST'])
@agencia_required
def agency_cerrar_leaderboard_semanal():
    agencia_id = session.get('agencia_id')
    config = PremioLeaderboard.query.filter_by(agencia_id=agencia_id).first()
    if not config:
        config = PremioLeaderboard(agencia_id=agencia_id)
        db.session.add(config)
        db.session.commit()
    
    fecha_inicio = config.semanal_inicio_periodo
    if not fecha_inicio:
        hoy = datetime.utcnow()
        fecha_inicio = hoy - timedelta(days=hoy.weekday())
        fecha_inicio = fecha_inicio.replace(hour=0, minute=0, second=0, microsecond=0)
    
    objetivo = config.semanal_objetivo
    perfiles = Perfil.query.filter_by(agencia_id=agencia_id).all()
    ranking = []
    for perfil in perfiles:
        mensajes = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= fecha_inicio
        ).all()
        creditos = sum(m.creditos_generados for m in mensajes)
        if objetivo == 0 or creditos >= objetivo:
            ranking.append({'perfil_id': perfil.id, 'nombre': perfil.nombre, 'creditos': creditos})
    
    ranking.sort(key=lambda x: x['creditos'], reverse=True)
    
    fecha_fin = datetime.utcnow()
    premios_registrados = []
    
    if config.semanal_activo and len(ranking) >= 1 and ranking[0]['creditos'] > 0:
        gasto = GastoPremio(
            agencia_id=agencia_id,
            perfil_id=ranking[0]['perfil_id'],
            periodo='semanal',
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            puesto=1,
            premio_usd=config.semanal_premio1,
            creditos_acumulados=ranking[0]['creditos']
        )
        db.session.add(gasto)
        premios_registrados.append({'modelo': ranking[0]['nombre'], 'puesto': 1, 'premio': config.semanal_premio1})
    
    if config.semanal_activo and len(ranking) >= 2 and ranking[1]['creditos'] > 0:
        gasto = GastoPremio(
            agencia_id=agencia_id,
            perfil_id=ranking[1]['perfil_id'],
            periodo='semanal',
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            puesto=2,
            premio_usd=config.semanal_premio2,
            creditos_acumulados=ranking[1]['creditos']
        )
        db.session.add(gasto)
        premios_registrados.append({'modelo': ranking[1]['nombre'], 'puesto': 2, 'premio': config.semanal_premio2})
    
    if config.semanal_activo and len(ranking) >= 3 and ranking[2]['creditos'] > 0:
        gasto = GastoPremio(
            agencia_id=agencia_id,
            perfil_id=ranking[2]['perfil_id'],
            periodo='semanal',
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            puesto=3,
            premio_usd=config.semanal_premio3,
            creditos_acumulados=ranking[2]['creditos']
        )
        db.session.add(gasto)
        premios_registrados.append({'modelo': ranking[2]['nombre'], 'puesto': 3, 'premio': config.semanal_premio3})
    
    config.semanal_ultimo_cierre = fecha_fin
    config.semanal_inicio_periodo = fecha_fin
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'premios_registrados': premios_registrados,
        'total_gastado': sum(p['premio'] for p in premios_registrados),
        'nuevo_periodo_inicio': fecha_fin.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/agency/api/leaderboard/cerrar-quincenal', methods=['POST'])
@agencia_required
def agency_cerrar_leaderboard_quincenal():
    agencia_id = session.get('agencia_id')
    config = PremioLeaderboard.query.filter_by(agencia_id=agencia_id).first()
    if not config:
        config = PremioLeaderboard(agencia_id=agencia_id)
        db.session.add(config)
        db.session.commit()
    
    fecha_inicio = config.quincenal_inicio_periodo
    if not fecha_inicio:
        hoy = datetime.utcnow()
        if hoy.day < 16:
            fecha_inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            fecha_inicio = hoy.replace(day=16, hour=0, minute=0, second=0, microsecond=0)
    
    objetivo = config.quincenal_objetivo
    perfiles = Perfil.query.filter_by(agencia_id=agencia_id).all()
    ranking = []
    for perfil in perfiles:
        mensajes = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= fecha_inicio
        ).all()
        creditos = sum(m.creditos_generados for m in mensajes)
        if objetivo == 0 or creditos >= objetivo:
            ranking.append({'perfil_id': perfil.id, 'nombre': perfil.nombre, 'creditos': creditos})
    
    ranking.sort(key=lambda x: x['creditos'], reverse=True)
    
    fecha_fin = datetime.utcnow()
    premios_registrados = []
    
    if config.quincenal_activo and len(ranking) >= 1 and ranking[0]['creditos'] > 0:
        gasto = GastoPremio(
            agencia_id=agencia_id,
            perfil_id=ranking[0]['perfil_id'],
            periodo='quincenal',
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            puesto=1,
            premio_usd=config.quincenal_premio1,
            creditos_acumulados=ranking[0]['creditos']
        )
        db.session.add(gasto)
        premios_registrados.append({'modelo': ranking[0]['nombre'], 'puesto': 1, 'premio': config.quincenal_premio1})
    
    if config.quincenal_activo and len(ranking) >= 2 and ranking[1]['creditos'] > 0:
        gasto = GastoPremio(
            agencia_id=agencia_id,
            perfil_id=ranking[1]['perfil_id'],
            periodo='quincenal',
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            puesto=2,
            premio_usd=config.quincenal_premio2,
            creditos_acumulados=ranking[1]['creditos']
        )
        db.session.add(gasto)
        premios_registrados.append({'modelo': ranking[1]['nombre'], 'puesto': 2, 'premio': config.quincenal_premio2})
    
    if config.quincenal_activo and len(ranking) >= 3 and ranking[2]['creditos'] > 0:
        gasto = GastoPremio(
            agencia_id=agencia_id,
            perfil_id=ranking[2]['perfil_id'],
            periodo='quincenal',
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            puesto=3,
            premio_usd=config.quincenal_premio3,
            creditos_acumulados=ranking[2]['creditos']
        )
        db.session.add(gasto)
        premios_registrados.append({'modelo': ranking[2]['nombre'], 'puesto': 3, 'premio': config.quincenal_premio3})
    
    config.quincenal_ultimo_cierre = fecha_fin
    config.quincenal_inicio_periodo = fecha_fin
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'premios_registrados': premios_registrados,
        'total_gastado': sum(p['premio'] for p in premios_registrados),
        'nuevo_periodo_inicio': fecha_fin.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/agency/api/leaderboard/cerrar-mensual', methods=['POST'])
@agencia_required
def agency_cerrar_leaderboard_mensual():
    agencia_id = session.get('agencia_id')
    config = PremioLeaderboard.query.filter_by(agencia_id=agencia_id).first()
    if not config:
        config = PremioLeaderboard(agencia_id=agencia_id)
        db.session.add(config)
        db.session.commit()
    
    fecha_inicio = config.mensual_inicio_periodo
    if not fecha_inicio:
        hoy = datetime.utcnow()
        fecha_inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    objetivo = config.mensual_objetivo
    perfiles = Perfil.query.filter_by(agencia_id=agencia_id).all()
    ranking = []
    for perfil in perfiles:
        mensajes = Mensaje.query.filter(
            (Mensaje.emisor_perfil_id == perfil.id) | (Mensaje.receptor_perfil_id == perfil.id),
            Mensaje.fecha >= fecha_inicio
        ).all()
        creditos = sum(m.creditos_generados for m in mensajes)
        if objetivo == 0 or creditos >= objetivo:
            ranking.append({'perfil_id': perfil.id, 'nombre': perfil.nombre, 'creditos': creditos})
    
    ranking.sort(key=lambda x: x['creditos'], reverse=True)
    
    fecha_fin = datetime.utcnow()
    premios_registrados = []
    
    if config.mensual_activo and len(ranking) >= 1 and ranking[0]['creditos'] > 0:
        gasto = GastoPremio(
            agencia_id=agencia_id,
            perfil_id=ranking[0]['perfil_id'],
            periodo='mensual',
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            puesto=1,
            premio_usd=config.mensual_premio1,
            creditos_acumulados=ranking[0]['creditos']
        )
        db.session.add(gasto)
        premios_registrados.append({'modelo': ranking[0]['nombre'], 'puesto': 1, 'premio': config.mensual_premio1})
    
    if config.mensual_activo and len(ranking) >= 2 and ranking[1]['creditos'] > 0:
        gasto = GastoPremio(
            agencia_id=agencia_id,
            perfil_id=ranking[1]['perfil_id'],
            periodo='mensual',
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            puesto=2,
            premio_usd=config.mensual_premio2,
            creditos_acumulados=ranking[1]['creditos']
        )
        db.session.add(gasto)
        premios_registrados.append({'modelo': ranking[1]['nombre'], 'puesto': 2, 'premio': config.mensual_premio2})
    
    if config.mensual_activo and len(ranking) >= 3 and ranking[2]['creditos'] > 0:
        gasto = GastoPremio(
            agencia_id=agencia_id,
            perfil_id=ranking[2]['perfil_id'],
            periodo='mensual',
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            puesto=3,
            premio_usd=config.mensual_premio3,
            creditos_acumulados=ranking[2]['creditos']
        )
        db.session.add(gasto)
        premios_registrados.append({'modelo': ranking[2]['nombre'], 'puesto': 3, 'premio': config.mensual_premio3})
    
    config.mensual_ultimo_cierre = fecha_fin
    config.mensual_inicio_periodo = fecha_fin
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'premios_registrados': premios_registrados,
        'total_gastado': sum(p['premio'] for p in premios_registrados),
        'nuevo_periodo_inicio': fecha_fin.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/agency/api/gastos-premios', methods=['GET'])
@agencia_required
def agency_get_gastos_premios():
    agencia_id = session.get('agencia_id')
    gastos = GastoPremio.query.filter_by(agencia_id=agencia_id).order_by(GastoPremio.fecha_pago.desc()).limit(50).all()
    
    return jsonify([{
        'id': g.id,
        'modelo_nombre': g.perfil.nombre,
        'periodo': g.periodo,
        'puesto': g.puesto,
        'premio_usd': g.premio_usd,
        'creditos_acumulados': g.creditos_acumulados,
        'fecha_pago': g.fecha_pago.strftime('%Y-%m-%d %H:%M:%S'),
        'fecha_inicio': g.fecha_inicio.strftime('%Y-%m-%d'),
        'fecha_fin': g.fecha_fin.strftime('%Y-%m-%d')
    } for g in gastos])

# ============================
# RUTAS DE CLIENTE Y MODELO
# ============================
@app.route('/app')
@login_required
def app_main():
    if session.get('tipo') != 'cliente': 
        return redirect('/')
    cliente = Cliente.query.get(session['user_id'])
    perfiles = Perfil.query.filter(Perfil.edad >= cliente.edad_min, Perfil.edad <= cliente.edad_max).all()
    return render_template('usuario.html', cliente=cliente, perfiles=perfiles)

@app.route('/perfil_cliente')
@login_required
def perfil_cliente():
    if session.get('tipo') != 'cliente': 
        return redirect('/')
    cliente = Cliente.query.get(session['user_id'])
    galeria = ClienteFoto.query.filter_by(cliente_id=cliente.id).order_by(ClienteFoto.fecha_subida.desc()).all()
    return render_template('perfil_cliente_v2.html', cliente=cliente, galeria=galeria)

@app.route('/chat_cliente/<string:public_id>')
@login_required
def chat_cliente(public_id):
    if session.get('tipo') != 'cliente': 
        return redirect('/')
    cliente = Cliente.query.get(session['user_id'])
    perfil = Perfil.query.filter_by(public_id=public_id).first_or_404()
    fotos = Foto.query.filter_by(perfil_id=perfil.id).all()
    perfil.fotos = fotos
    return render_template('chat_cliente_ws.html', cliente=cliente, perfil=perfil)

@app.route('/people/<string:public_id>')
@modelo_required
def people(public_id):
    perfil = Perfil.query.filter_by(public_id=public_id).first_or_404()
    if session.get('perfil_id') != perfil.id:
        abort(403)
    visitor_id = request.args.get('visitor', type=str)
    cliente_actual = Cliente.query.filter_by(public_id=visitor_id).first() if visitor_id else None
    perfil.is_online = True
    perfil.ultima_conexion = datetime.utcnow()
    perfil.ultima_ip = request.remote_addr
    db.session.commit()
    return render_template('chat_modelo_ws.html', perfil=perfil, cliente_actual=cliente_actual, stats={})

@app.route('/api/toggle_online', methods=['POST'])
@modelo_required
def api_toggle_online():
    perfil = Perfil.query.get(session['perfil_id'])
    perfil.is_online = not perfil.is_online
    db.session.commit()
    return jsonify({'success': True, 'is_online': perfil.is_online})

@app.route('/api/enviar_mensaje', methods=['POST'])
@login_required
def api_enviar_mensaje():
    data = request.get_json()
    contenido = data.get('contenido', '').strip()
    receptor_public_id = data.get('receptor_public_id')
    es_regalo = data.get('es_regalo', False)
    regalo_id = data.get('regalo_id')
    
    if not contenido or not receptor_public_id:
        return jsonify({'success': False, 'msg': 'Datos incompletos'}), 400
    
    es_scam, motivo = detectar_scam(contenido)
    if es_scam: 
        return jsonify({'success': False, 'msg': motivo}), 403
        
    if session.get('tipo') == 'cliente':
        cliente = Cliente.query.get(session['user_id'])
        perfil = Perfil.query.filter_by(public_id=receptor_public_id).first()
        if not perfil:
            return jsonify({'success': False, 'msg': 'Perfil no encontrado'}), 404
        
        if es_regalo and regalo_id:
            regalo = Regalo.query.get(regalo_id)
            if not regalo or not regalo.activo:
                return jsonify({'success': False, 'msg': 'Regalo no disponible'}), 400
            costo_creditos = regalo.costo_creditos
            creditos_ganancia = costo_creditos
        else:
            rate = obtener_rate('chat')
            costo_creditos = rate.creditos_costo
            creditos_ganancia = rate.creditos_ganancia_modelo
        
        if cliente.creditos < costo_creditos:
            return jsonify({'success': False, 'msg': 'Sin créditos suficientes'}), 403
            
        mensaje = Mensaje(
            contenido=contenido, 
            tipo_emisor='cliente', 
            emisor_cliente_id=cliente.id, 
            receptor_perfil_id=perfil.id, 
            creditos_generados=creditos_ganancia,
            es_regalo=es_regalo,
            regalo_id=regalo_id if es_regalo else None
        )
        cliente.creditos -= costo_creditos
        perfil.creditos_generados += creditos_ganancia
        db.session.add(mensaje)
        db.session.commit()
        
        sala_chat = f"modelo_{perfil.id}"
        socketio.emit('nuevo_mensaje', {'id': mensaje.id, 'contenido': contenido, 'tipo_emisor': 'cliente', 'timestamp': mensaje.fecha.isoformat(), 'emisor_public_id': cliente.public_id, 'receptor_public_id': perfil.public_id, 'es_regalo': es_regalo}, room=sala_chat)
        return jsonify({'success': True, 'balance': cliente.creditos, 'mensaje_id': mensaje.id})
        
    elif session.get('tipo') == 'modelo':
        perfil = Perfil.query.get(session['perfil_id'])
        cliente = Cliente.query.filter_by(public_id=receptor_public_id).first()
        if not cliente:
            return jsonify({'success': False, 'msg': 'Cliente no encontrado'}), 404
            
        mensaje = Mensaje(contenido=contenido, tipo_emisor='modelo', emisor_perfil_id=perfil.id, receptor_cliente_id=cliente.id, creditos_generados=0)
        db.session.add(mensaje)
        db.session.commit()
        
        sala_chat = f"modelo_{perfil.id}"
        socketio.emit('nuevo_mensaje', {'id': mensaje.id, 'contenido': contenido, 'tipo_emisor': 'modelo', 'timestamp': mensaje.fecha.isoformat(), 'emisor_public_id': perfil.public_id, 'receptor_public_id': cliente.public_id}, room=sala_chat)
        return jsonify({'success': True, 'mensaje_id': mensaje.id})
        
    return jsonify({'success': False}), 403

@app.route('/api/get_mensajes/<string:contacto_public_id>')
@login_required
def api_get_mensajes(contacto_public_id):
    if session.get('tipo') == 'cliente':
        cliente = Cliente.query.get(session['user_id'])
        perfil = Perfil.query.filter_by(public_id=contacto_public_id).first()
        if not perfil:
            return jsonify([])
        mensajes = Mensaje.query.filter(((Mensaje.emisor_cliente_id == cliente.id) & (Mensaje.receptor_perfil_id == perfil.id)) | ((Mensaje.emisor_perfil_id == perfil.id) & (Mensaje.receptor_cliente_id == cliente.id))).order_by(Mensaje.fecha.asc()).all()
    else:
        return jsonify([])
    return jsonify([{'id': m.id, 'contenido': m.contenido, 'fecha': m.fecha.isoformat(), 'tipo_emisor': m.tipo_emisor, 'es_regalo': m.es_regalo} for m in mensajes])

# ============================
# WEBSOCKETS
# ============================
@socketio.on('join')
def handle_join(data):
    room = data.get('room')
    if room:
        join_room(room)

@socketio.on('enviar_regalo')
def handle_regalo(data):
    if session.get('tipo') != 'cliente':
        return
    room = data.get('room')
    regalo_id = data.get('regalo_id')
    receptor_public_id = data.get('receptor_public_id')
    
    regalo = Regalo.query.get(regalo_id)
    if not regalo or not regalo.activo:
        return
    
    cliente = Cliente.query.get(session['user_id'])
    perfil = Perfil.query.filter_by(public_id=receptor_public_id).first()
    
    if cliente and perfil and cliente.creditos >= regalo.costo_creditos:
        cliente.creditos -= regalo.costo_creditos
        perfil.creditos_generados += regalo.costo_creditos
        db.session.commit()
        
        emit('recibir_regalo', {'regalo': regalo.emoji, 'nombre': regalo.nombre, 'emisor': cliente.nombre_real, 'emisor_public_id': cliente.public_id}, room=room)
        emit('actualizar_balance', {'creditos': cliente.creditos}, to=request.sid)

# ============================
# INICIO DE LA APLICACIÓN
# ============================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_rates()
        
        if not Admin.query.filter_by(email='master@amura.com').first():
            super_admin = Admin(nombre='Super Admin', email='master@amura.com', password_hash=generate_password_hash('Amura2024!Secure'))
            db.session.add(super_admin)
            db.session.commit()
            print("✅ Superadmin creado: master@amura.com / Amura2024!Secure")
        
        if not ConfigGlobal.query.filter_by(clave='valor_credito_usd').first():
            ConfigGlobal.set('valor_credito_usd', '0.10', 'Valor de 1 crédito en USD')
        if not ConfigGlobal.query.filter_by(clave='comision_plataforma_base').first():
            ConfigGlobal.set('comision_plataforma_base', '60', 'Comisión base que retiene la plataforma (%)')
        if not ConfigGlobal.query.filter_by(clave='comision_agencia_base').first():
            ConfigGlobal.set('comision_agencia_base', '25', 'Comisión base que recibe la agencia (%)')
        if not ConfigGlobal.query.filter_by(clave='comision_modelo_base').first():
            ConfigGlobal.set('comision_modelo_base', '15', 'Comisión base que recibe la modelo (%)')
        
        regalos_default = [
            {'nombre': 'Rosa', 'emoji': '🌹', 'costo': 20, 'orden': 1},
            {'nombre': 'Corazón', 'emoji': '❤️', 'costo': 10, 'orden': 2},
            {'nombre': 'Beso', 'emoji': '💋', 'costo': 15, 'orden': 3},
            {'nombre': 'Oso de Peluche', 'emoji': '🧸', 'costo': 30, 'orden': 4},
            {'nombre': 'Diamante', 'emoji': '💎', 'costo': 50, 'orden': 5},
            {'nombre': 'Coche Deportivo', 'emoji': '🏎️', 'costo': 200, 'orden': 6},
            {'nombre': 'Mansión', 'emoji': '🏰', 'costo': 500, 'orden': 7},
            {'nombre': 'Yate', 'emoji': '🛥️', 'costo': 1000, 'orden': 8},
        ]
        for r in regalos_default:
            if not Regalo.query.filter_by(nombre=r['nombre']).first():
                nuevo = Regalo(nombre=r['nombre'], emoji=r['emoji'], costo_creditos=r['costo'], orden=r['orden'], activo=True)
                db.session.add(nuevo)
        db.session.commit()
        
        print("✅ Base de datos inicializada correctamente")
    
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)