from app.models import User, db
from main import app

with app.app_context():
    # Cambia estos datos por el usuario y contraseña que quieras usar
    username = "admin"
    password = "adminpassword123"

    user = User.query.filter_by(username=username).first()

    if user:
        print(f"El usuario '{username}' ya existe. Actualizando contraseña...")
        user.set_password(password)
    else:
        print(f"Creando nuevo superusuario '{username}'...")
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)

    db.session.commit()
    print("--> ¡Superusuario listo para iniciar sesión!")
