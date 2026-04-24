USE exam_platform;

CREATE TABLE IF NOT EXISTS grading_jobs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    exam_id INT NOT NULL,
    status ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending',
    total_students INT DEFAULT 0,
    processed_students INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (exam_id) REFERENCES exams(exam_id) ON DELETE CASCADE
) COMMENT 'AI阅卷任务记录表';
