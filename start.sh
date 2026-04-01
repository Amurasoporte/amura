#!/bin/bash
# Esperar a que la base de datos esté lista
echo "🚀 Iniciando Amura..."

# Crear tablas y superadmin
python3 -c "
from app import app, db
from app import Agencia
from werkzeug.security import generate_password_hash

with app.app_context():
    print('📦 Creando tablas...')
    db.create_all()
    print('✅ Tablas creadas')
    
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
        print('✅ Superadmin creado: master@amura.com / master123')
    else:
        print('✅ Superadmin ya existe')
"

# Iniciar Gunicorn
echo "🚀 Iniciando servidor..."
exec gunicorn --bind 0.0.0.0:$PORT app:app
