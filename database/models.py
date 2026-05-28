from sqlalchemy import Column, Integer, String, Float, ForeignKey, Text, DateTime, Index, func
from sqlalchemy.orm import relationship
from database.db_connect import Base
from pgvector.sqlalchemy import Vector


class College(Base):
    __tablename__ = "colleges"
    name = Column(String, primary_key=True, index=True)

    departments = relationship("Department", back_populates="college")

class Department(Base):
    __tablename__ = "departments"
    name = Column(String, primary_key=True, index=True)
    college_name = Column(String, ForeignKey("colleges.name"), nullable=False)

    college = relationship("College", back_populates="departments")
    courses = relationship("Course", back_populates="department")

class Course(Base):
    __tablename__ = "courses"
    serial_no = Column(String, primary_key=True, index=True)
    class_no = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)

    credit = Column(Float, nullable=False)
    password_card = Column(String, nullable=True)

    teachers = Column(Text, nullable=True) # comma-separated or JSON
    class_times = Column(Text, nullable=True) # comma-separated or JSON

    limit_cnt = Column(Integer, nullable=True)
    admit_cnt = Column(Integer, nullable=True)
    wait_cnt = Column(Integer, nullable=True)

    college_name = Column(String, ForeignKey("colleges.name"), nullable=True)
    department_name = Column(String, ForeignKey("departments.name"), nullable=True)
    course_type = Column(String, nullable=True) # e.g. REQUIRED, ELECTIVE

    department = relationship("Department", back_populates="courses")
    college = relationship("College")
    detail = relationship("CourseDetail", back_populates="course", uselist=False, cascade="all, delete-orphan")
    course_embedding = relationship("CourseEmbedding", back_populates="course", uselist=False, cascade="all, delete-orphan")

class CourseDetail(Base):
    __tablename__ = "course_details"

    serial_no = Column(String, ForeignKey("courses.serial_no", ondelete="CASCADE"), primary_key=True, index=True)
    objectives = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    books = Column(Text, nullable=True)
    teaching_method = Column(Text, nullable=True)
    grading_policy = Column(Text, nullable=True)

    course = relationship("Course", back_populates="detail")

class CourseEmbedding(Base):
    __tablename__ = "course_embeddings"

    serial_no = Column(String, ForeignKey("courses.serial_no", ondelete="CASCADE"), primary_key=True, index=True)
    organized_description = Column(Text, nullable=False)
    embedding = Column(Vector(768), nullable=True)

    course = relationship("Course", back_populates="course_embedding")

    __table_args__ = (
        Index(
            "ix_course_embeddings_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )



class SystemStatus(Base):
    __tablename__ = "system_status"
    id = Column(Integer, primary_key=True, index=True)
    last_course_sync = Column(DateTime(timezone=True), nullable=True)
    last_scholarship_sync = Column(DateTime(timezone=True), nullable=True)

class Scholarship(Base):
    __tablename__ = "scholarships"
    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String, index=True, nullable=False) # e.g. 獎學金, 招募資訊
    title = Column(String, nullable=False)
    content_summary = Column(Text, nullable=True)
    download_link = Column(String, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)  # NCU Portal unique `identifier`
    chinese_name = Column(String, nullable=True)
    english_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    role = Column(String, default="student")          # 'student', 'faculty', 'admin'
    student_id = Column(String, unique=True, index=True, nullable=True)
    department = Column(String, nullable=True)         # Extracted from academy-records/faculty-records
    study_system = Column(String, nullable=True)
    student_status = Column(String, nullable=True)
    employee_type = Column(String, nullable=True)
    employee_status = Column(String, nullable=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    courses = relationship("UserCourse", back_populates="user", cascade="all, delete-orphan")
    documents = relationship("UserDocument", back_populates="user", cascade="all, delete-orphan")
    messages = relationship("ChatMessage", back_populates="user", cascade="all, delete-orphan")


class UserCourse(Base):
    __tablename__ = "user_courses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    serial_no = Column(String, ForeignKey("courses.serial_no", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    user = relationship("User", back_populates="courses")
    course = relationship("Course")


class UserDocument(Base):
    __tablename__ = "user_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    raw_content = Column(Text, nullable=False)
    status = Column(String, default="processing")  # 'processing', 'ready', 'error'
    created_at = Column(DateTime, default=func.now())

    # Relationships
    user = relationship("User", back_populates="documents")
    chunks = relationship("UserDocumentChunk", back_populates="document", cascade="all, delete-orphan")


class UserDocumentChunk(Base):
    __tablename__ = "user_document_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(Integer, ForeignKey("user_documents.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(768), nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    document = relationship("UserDocument", back_populates="chunks")
    user = relationship("User")

    __table_args__ = (
        Index(
            "ix_user_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # 'user', 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    user = relationship("User", back_populates="messages")
