from sqlalchemy import Column, Integer, String, Float, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from database.db_connect import Base

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

class CourseDetail(Base):
    __tablename__ = "course_details"

    serial_no = Column(String, ForeignKey("courses.serial_no", ondelete="CASCADE"), primary_key=True, index=True)
    objectives = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    books = Column(Text, nullable=True)
    teaching_method = Column(Text, nullable=True)
    grading_policy = Column(Text, nullable=True)

    course = relationship("Course", back_populates="detail")

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
