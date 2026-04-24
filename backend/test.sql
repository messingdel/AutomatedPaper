SELECT id, file_path, REPLACE(file_path, 'uploads/', '') AS new_path
FROM answer_sheets
WHERE file_path LIKE 'uploads/%';
