"""
資料庫模組
----------
SQLAlchemy engine / SessionLocal / Base、所有資料表 Model，以及 FastAPI 用的 get_db 依賴。

這支檔案不 import main，其他模組可以直接 `from core.database import ...` 使用。
Geofence / GeofenceEvent 兩張表在本檔下方呼叫 geofence.init_models(Base) 註冊；
Base.metadata.create_all() 留在 main.py。
"""
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table, Boolean, Text
# [修正 2026-11-26] 加 backref（User.managed_users 關聯修正用）
# 原本：from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, backref

SQLALCHEMY_DATABASE_URL = "sqlite:///./mezzo.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

user_device_link = Table(
    'user_device_link', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('device_id', Integer, ForeignKey('devices.id'), primary_key=True)
)

class User(Base):
    __tablename__ = 'users'
    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String, unique=True, index=True)
    password      = Column(String)
    email         = Column(String, nullable=True)
    role          = Column(String, default="operator")
    whatsapp      = Column(String, nullable=True)
    manager_id    = Column(Integer, ForeignKey('users.id'), nullable=True)
    # [修正 2026-11-26] 原本這個關聯方向相反：remote_side=[id] 放在 managed_users 上，讓它變成多對一，結果
    #   u.managed_users 拿到的是「u 的管理者」（單一 User 或 None），u.manager 拿到的是「u 管理的人」（list）。
    #   造成：有人被指派管理者後 GET /api/users（features/users.py 的 u.manager.username）回 500；
    #   group_manager 查設備（api/v1.py 的 _get_user_devices、features/devices.py 的 get_devices）
    #   `for u in user.managed_users` 會 TypeError → 500。
    # 改成 remote_side 放在 backref 的 manager 上：managed_users ＝ 一對多（u 管理的人，list），manager ＝ 多對一（u 的管理者）。
    # 用到這兩個名稱的地方本來就是照這個意思寫的，不用改；資料表結構（manager_id 欄位）不變，不需要遷移。
    # 原本：managed_users = relationship("User", backref="manager", remote_side=[id])
    managed_users = relationship("User", backref=backref("manager", remote_side=[id]))
    devices       = relationship("Device", secondary=user_device_link, backref="users")

class Device(Base):
    __tablename__ = 'devices'
    id        = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, index=True)
    name      = Column(String)
    mjpeg_url = Column(String)

class NVRConfig(Base):
    __tablename__ = 'nvr_config'
    id        = Column(Integer, primary_key=True)
    ip        = Column(String,  default='127.0.0.1')
    http_port = Column(Integer, default=80)
    rtsp_port = Column(Integer, default=2554)
    username  = Column(String,  default='Admin')
    password  = Column(String,  default='1234')

class MqttConfig(Base):
    __tablename__ = 'mqtt_config'
    id   = Column(Integer, primary_key=True)
    ip   = Column(String,  default='118.163.141.80')
    port = Column(Integer, default=1688)

class SocialMediaConfig(Base):
    __tablename__ = 'social_media_config'
    id             = Column(Integer, primary_key=True)
    provider       = Column(String,  default="meta")
    access_token   = Column(String,  default="")
    phone_number_id = Column(String, default="")
    account_sid    = Column(String,  default="")
    public_url     = Column(String,  default="")
    stt_keyword    = Column(String,  default="影像傳送")
    is_enabled     = Column(Boolean, default=False)

class TakServerConfig(Base):
    __tablename__ = 'tak_server_config'
    id         = Column(Integer, primary_key=True)
    host       = Column(String,  default='')
    port       = Column(Integer, default=8087)
    enabled    = Column(Boolean, default=False)
    callsign   = Column(String,  default='Mezzo-EOC')

class GpsRecord(Base):
    __tablename__ = 'gps_records'
    id        = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    lat       = Column(String)
    lng       = Column(String)
    battery   = Column(Integer, default=0)
    status    = Column(String, default="")
    source    = Column(String, default="mqtt")
    timestamp = Column(String, index=True)

class WhatsAppLog(Base):
    __tablename__ = 'whatsapp_logs'
    id               = Column(Integer, primary_key=True, index=True)
    timestamp        = Column(String)
    device_id        = Column(String)
    source           = Column(String, default="mqtt")
    transcript       = Column(Text, default="")
    keyword_detected = Column(Boolean, default=False)
    stream_url       = Column(String, default="")
    recipients       = Column(String, default="")
    status           = Column(String, default="pending")

class SosRecord(Base):
    __tablename__ = 'sos_records'
    id        = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    channel   = Column(String, default='')
    lat       = Column(String, default='0')
    lng       = Column(String, default='0')
    timestamp = Column(String, index=True)

class PttRecord(Base):
    __tablename__ = 'ptt_records'
    id        = Column(Integer, primary_key=True, index=True)
    group_id  = Column(Integer)
    sender    = Column(String)
    text      = Column(String)
    text_zh   = Column(String, default="")
    text_en   = Column(String, default="")
    audio_url = Column(String)
    timestamp = Column(String)


# Geofence / GeofenceEvent 定義在 geofence.py，在這裡註冊。
# 一定要放在 database.py 而不是 main.py：python main.py（reload 模式）會讓 main.py 被執行兩次，
# 但 database 模組只會載入一次，放這裡才能保證同一個 Base 只註冊一次。
# （geofence.py 不 import database / main，所以沒有循環匯入）
# [搬移] geofence.py 搬到 features/geofence.py。原本：import geofence
from features import geofence
Geofence, GeofenceEvent = geofence.init_models(Base)


def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
