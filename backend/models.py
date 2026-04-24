from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Enum, Boolean, ForeignKey
from sqlalchemy.sql import func
from backend.database import Base

class Exam(Base):
    __tablename__ = 'exams'
    __table_args__ = {'extend_existing': True}
    exam_id = Column(Integer, primary_key=True, autoincrement=True)
    exam_name = Column(String(255), nullable=False)
    description = Column(Text)
    exam_date = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    status = Column(Enum('created', 'uploading', 'processing', 'completed', 'graded'), default='created')
    total_questions = Column(Integer)
    total_score = Column(Integer)

class Student(Base):
    __tablename__ = 'students'
    __table_args__ = {'extend_existing': True}
    student_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    student_number = Column(String(50), unique=True)
    class_ = Column('class', String(100))
    contact_info = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class ExamStudent(Base):
    __tablename__ = 'exam_students'
    __table_args__ = {'extend_existing': True}
    exam_student_id = Column(Integer, primary_key=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey('exams.exam_id', ondelete='CASCADE'))
    student_id = Column(Integer, ForeignKey('students.student_id', ondelete='CASCADE'))
    assigned_at = Column(DateTime, server_default=func.now())
    sort_order = Column(Integer, default=0)

class Question(Base):
    __tablename__ = 'questions'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False)
    content = Column(Text)
    score = Column(Float, default=0)
    reference_answer = Column(Text)
    scoring_rules = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class ExamQuestion(Base):
    __tablename__ = 'exam_questions'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(Integer, ForeignKey('questions.id', ondelete='CASCADE'))
    exam_id = Column(Integer, ForeignKey('exams.exam_id', ondelete='CASCADE'))
    question_order = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

class User(Base):
    __tablename__ = 'users'
    __table_args__ = {'extend_existing': True}
    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100), unique=True)
    role = Column(Enum('admin', 'teacher', 'student'), default='teacher')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime)

class AnswerSheet(Base):
    __tablename__ = 'answer_sheets'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey('exams.exam_id', ondelete='CASCADE'))
    student_id = Column(Integer, ForeignKey('students.student_id', ondelete='CASCADE'))
    filename = Column(String(255), nullable=False)      # 对应原 filename
    file_path = Column(String(500), nullable=False)     # 对应原 file_path
    uploaded_at = Column(DateTime, server_default=func.now())
    page_order = Column(Integer, default=0)  # 新增

class Score(Base):
    __tablename__ = 'student_scores'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey('exams.exam_id', ondelete='CASCADE'))
    student_id = Column(Integer, ForeignKey('students.student_id', ondelete='CASCADE'))
    question_id = Column(Integer, ForeignKey('questions.id', ondelete='CASCADE'))
    score = Column(Float, nullable=False)
    feedback = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

