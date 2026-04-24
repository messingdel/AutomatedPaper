<template>
  <div class="answer-manager">
    <!-- 工具栏 -->
    <div class="tab-actions">
      <el-button type="primary" @click="openUploadDialog">上传图片</el-button>
      <el-button @click="fetchStudentImages">刷新</el-button>
      <el-button type="success" @click="handleImportFolder">导入文件夹</el-button>
    </div>

    <!-- 学生表格（每个学生一行，展示其多张图片） -->
    <el-table :data="studentList" style="width: 100%" row-key="student_id">
      <el-table-column prop="student_number" label="学号" width="120" />
      <el-table-column prop="name" label="姓名" width="100" />
      <el-table-column prop="class" label="班级" width="120" />
      <el-table-column label="答题卡图片" min-width="400">
        <template #default="{ row }">
          <div
              class="images-container"
              @dragover.prevent
              @drop="handleDrop($event, row.student_id)"
          >
            <div
              v-for="img in row.images"
              :key="img.id"
              class="image-item"
              draggable="true"
              @dragstart="handleDragStart($event, img, row.student_id)"
              @dragend="handleDragEnd"
            >
              <el-image
                :src="getImageUrl(img.file_path)"
                fit="cover"
                class="image-thumb"
                :preview-src-list="[getImageUrl(img.file_path)]"
              />
              <div class="image-actions">
                <el-input-number
                  v-model="img.page_order"
                  :min="0"
                  size="small"
                  controls-position="right"
                  @change="updateImageOrder(img)"
                  style="width: 100px"
                />
                <el-button
                  type="danger"
                  size="small"
                  @click="deleteImage(img.id)"
                >删除</el-button>
              </div>
              <div class="image-filename">{{ img.filename }}</div>
            </div>
            <!-- 为该学生添加图片的按钮 -->
            <el-upload
              :auto-upload="false"
              :show-file-list="false"
              :on-change="(file) => handleAddFile(file, row.student_id)"
              multiple
              accept=".jpg,.jpeg,.png,.bmp"
            >
              <el-button type="primary" plain size="small">+ 添加图片</el-button>
            </el-upload>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 上传对话框（批量上传到指定学生） -->
    <el-dialog v-model="showUploadDialog" title="上传答题卡图片" width="600px">
      <el-form label-width="100px">
        <el-form-item label="选择学生">
          <el-select v-model="uploadStudentId" placeholder="请选择学生" filterable>
            <el-option
              v-for="s in studentList"
              :key="s.student_id"
              :label="`${s.name} (${s.student_number || '无学号'})`"
              :value="s.student_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="图片文件">
          <el-upload
            ref="uploadRef"
            v-model:file-list="uploadFileList"
            :auto-upload="false"
            multiple
            accept=".jpg,.jpeg,.png,.bmp"
            :limit="20"
          >
            <el-button>选择文件</el-button>
            <template #tip>
              <div class="el-upload__tip">可多选，每张图片将按顺序分配页码（0,1,2...）</div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showUploadDialog = false">取消</el-button>
        <el-button type="primary" @click="uploadImages">确认上传</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const props = defineProps({
  examId: {
    type: String,
    required: true
  },
  students: {
    type: Array,
    default: () => []   // 默认空数组，避免 undefined
  }
})

// 学生列表（每个学生包含其图片数组）
const studentList = ref([])

// 上传对话框相关
const showUploadDialog = ref(false)
const uploadStudentId = ref(null)
const uploadFileList = ref([])

// 上传文件夹内容
const folderUploading = ref(false)

// 拖拽相关状态
const draggingImage = ref(null)
const draggingSourceStudentId = ref(null)

// 获取图片基础URL
const getImageUrl = (filePath) => {
  // 如果 filePath 已经是相对路径（如 "answer_sheets/1/xxx.jpg"），直接拼接
  // 或者如果包含 "uploads/" 前缀，则去掉后拼接
  let relative = filePath;
  if (relative.startsWith('./')) relative = relative.slice(2);
  if (relative.startsWith('uploads/')) relative = relative.slice(8);
  return `http://localhost:8001/uploads/${relative}`;
}

// 获取考试所有学生的图片并组装数据
const fetchStudentImages = async () => {
  try {
    // 1. 获取该考试的所有学生（通过后端接口，假设已有 /api/exams/{examId}/students）
    const studentsRes = await axios.get(`http://localhost:8001/api/exams/${props.examId}/students`)
    if (studentsRes.data.code !== 1) {
      ElMessage.error('获取学生列表失败')
      return
    }
    const students = studentsRes.data.data

    // 2. 获取该考试的所有图片
    const imagesRes = await axios.get(`http://localhost:8001/api/exams/${props.examId}/images`)
    if (imagesRes.data.code !== 1) {
      ElMessage.error('获取图片列表失败')
      return
    }
    const images = imagesRes.data.data

    // 3. 按学生分组图片
    const imgMap = new Map()
    for (const img of images) {
      const sid = img.student.student_id
      if (!imgMap.has(sid)) imgMap.set(sid, [])
      imgMap.get(sid).push(img)
    }

    // 4. 组装学生列表，每个学生附带其图片（并按 page_order 排序）
    const list = students.map(student => ({
      ...student,
      images: (imgMap.get(student.student_id) || []).sort((a, b) => a.page_order - b.page_order)
    }))
    studentList.value = list
  } catch (error) {
    console.error('获取数据失败:', error)
    ElMessage.error('获取数据失败')
  }
}

// 打开上传对话框
const openUploadDialog = () => {
  if (!studentList.value.length) {
    ElMessage.warning('请先导入学生名单')
    return
  }
  uploadStudentId.value = null
  uploadFileList.value = []
  showUploadDialog.value = true
}

// 上传图片
const uploadImages = async () => {
  if (!uploadStudentId.value) {
    ElMessage.error('请选择学生')
    return
  }
  if (uploadFileList.value.length === 0) {
    ElMessage.error('请选择图片文件')
    return
  }

  const formData = new FormData()
  for (const file of uploadFileList.value) {
    formData.append('files', file.raw)
  }
  formData.append('student_ids', uploadStudentId.value)

  try {
    const response = await axios.post(
      `http://localhost:8001/api/exams/${props.examId}/images`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
    if (response.data.code === 1) {
      ElMessage.success(`上传成功，共 ${response.data.data.uploaded_count} 个文件`)
      showUploadDialog.value = false
      uploadFileList.value = []
      await fetchStudentImages()
    } else {
      ElMessage.error(response.data.msg || '上传失败')
    }
  } catch (error) {
    console.error('上传失败:', error)
    ElMessage.error('上传失败')
  }
}

// 删除图片
const deleteImage = async (imageId) => {
  try {
    await ElMessageBox.confirm('确定删除该图片吗？', '提示', { type: 'warning' })
    const response = await axios.delete(`http://localhost:8001/api/exams/${props.examId}/images/${imageId}`)
    if (response.data.code === 1) {
      ElMessage.success('删除成功')
      await fetchStudentImages()
    } else {
      ElMessage.error(response.data.msg || '删除失败')
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除失败:', error)
      ElMessage.error('删除失败')
    }
  }
}

// 更新图片顺序
const updateImageOrder = async (img) => {
  const formData = new FormData()
  formData.append('page_order', img.page_order)
  try {
    const response = await axios.put(
      `http://localhost:8001/api/exams/${props.examId}/images/${img.id}`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
    if (response.data.code === 1) {
      ElMessage.success('顺序更新成功')
      await fetchStudentImages()
    } else {
      ElMessage.error(response.data.msg || '更新失败')
      await fetchStudentImages() // 刷新恢复原值
    }
  } catch (error) {
    console.error('更新顺序失败:', error)
    ElMessage.error('更新顺序失败')
    await fetchStudentImages()
  }
}

// 为某个学生单独添加图片（通过表格内的“添加图片”按钮）
const handleAddFile = async (file, studentId) => {
  const formData = new FormData()
  formData.append('files', file.raw)
  formData.append('student_ids', studentId)
  try {
    const response = await axios.post(
      `http://localhost:8001/api/exams/${props.examId}/images`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
    if (response.data.code === 1) {
      ElMessage.success('图片添加成功')
      await fetchStudentImages()
    } else {
      ElMessage.error(response.data.msg || '添加失败')
    }
  } catch (error) {
    console.error('添加图片失败:', error)
    ElMessage.error('添加图片失败')
  }
}

const fetchStudentList = async () => {
  try {
    const res = await axios.get(`/api/exams/${props.examId}/students`)
    if (res.data.code === 1) {
      studentList.value = res.data.data
    }
  } catch (error) {
    console.error('获取学生列表失败', error)
  }
}

// 处理文件夹导入
const handleImportFolder = async () => {
  // 优先使用 props.students，如果为空则使用内部获取的 studentList
  const students = (props.students && props.students.length) ? props.students : studentList.value
  if (!students || students.length === 0) {
    ElMessage.error('请先导入学生名单')
    return
  }

  const input = document.createElement('input')
  input.type = 'file'
  input.webkitdirectory = true
  input.directory = true
  input.multiple = true

  input.onchange = async (e) => {
    const files = Array.from(e.target.files)
    const imageFiles = files.filter(f => /\.(jpg|jpeg|png|bmp)$/i.test(f.name))
    if (imageFiles.length === 0) {
      ElMessage.error('文件夹中没有图片文件')
      return
    }

    const totalStudents = students.length   // 修正：使用 students
    const imagesPerStudent = 4
    const requiredImages = totalStudents * imagesPerStudent

    if (imageFiles.length < requiredImages) {
      ElMessage.error(`图片数量不足，需要 ${requiredImages} 张，实际 ${imageFiles.length} 张`)
      return
    }

    const groups = []
    for (let i = 0; i < totalStudents; i++) {
      const student = students[i]           // 修正：使用 students
      const startIdx = i * imagesPerStudent
      const studentImages = imageFiles.slice(startIdx, startIdx + imagesPerStudent)
      groups.push({ studentId: student.student_id, files: studentImages })
    }

    // 确认上传
    try {
      await ElMessageBox.confirm(
          `将为 ${totalStudents} 个学生各上传 ${imagesPerStudent} 张图片，共 ${requiredImages} 张。是否继续？`,
          '确认导入',
          { type: 'info' }
      )
    } catch {
      return
    }

    folderUploading.value = true
    let successCount = 0
    let failCount = 0

    for (const group of groups) {
      const formData = new FormData()
      for (const file of group.files) {
        formData.append('files', file)
      }
      formData.append('student_ids', group.studentId)

      try {
        const res = await axios.post(
            `/api/exams/${props.examId}/images`,
            formData,
            { headers: { 'Content-Type': 'multipart/form-data' } }
        )
        if (res.data.code === 1) {
          successCount += group.files.length
        } else {
          failCount += group.files.length
          console.error(`学生 ${group.studentId} 上传失败:`, res.data.msg)
        }
      } catch (err) {
        failCount += group.files.length
        console.error(`学生 ${group.studentId} 上传异常:`, err)
      }
    }

    folderUploading.value = false
    ElMessage.success(`上传完成：成功 ${successCount} 张，失败 ${failCount} 张`)
    // 刷新图片列表
    await fetchStudentImages()
  }

  input.click()
}

//拖拽操作
const handleDragStart = (event, img, sourceStudentId) => {
  draggingImage.value = img
  draggingSourceStudentId.value = sourceStudentId
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', JSON.stringify({
    id: img.id,
    sourceStudentId: sourceStudentId,
    filename: img.filename
  }))
}

const handleDragEnd = () => {
  // 不做任何清空，由 drop 事件负责清理
}

const handleDrop = async (event, targetStudentId) => {
  event.preventDefault()

  let image = draggingImage.value
  let sourceId = draggingSourceStudentId.value

  // 如果全局变量丢失，尝试从 dataTransfer 恢复
  if (!image) {
    const rawData = event.dataTransfer.getData('text/plain')
    if (rawData) {
      try {
        const { id, sourceStudentId, filename } = JSON.parse(rawData)
        image = { id, filename }
        sourceId = sourceStudentId
        // 重新赋值给全局变量，以便后续使用
        draggingImage.value = image
        draggingSourceStudentId.value = sourceId
      } catch (e) {
        console.error('恢复拖拽数据失败', e)
        return
      }
    } else {
      return
    }
  }

  if (!image || sourceId === targetStudentId) {
    // 清空状态并返回
    draggingImage.value = null
    draggingSourceStudentId.value = null
    return
  }

  // 确认移动
  try {
    await ElMessageBox.confirm(
        `将图片 "${image.filename}" 移动到 ${studentList.value.find(s => s.student_id === targetStudentId)?.name} 名下？`,
        '确认移动',
        { type: 'info' }
    )
  } catch {
    draggingImage.value = null
    draggingSourceStudentId.value = null
    return
  }

  // 调用后端接口
  try {
    const res = await axios.put(
        `http://localhost:8001/api/exams/${props.examId}/images/${image.id}/transfer`,
        null,
        { params: { target_student_id: targetStudentId } }
    )
    if (res.data.code === 1) {
      ElMessage.success('图片已移动')
      await fetchStudentImages()
    } else {
      ElMessage.error(res.data.msg || '移动失败')
    }
  } catch (error) {
    console.error('移动图片失败:', error)
    ElMessage.error('移动图片失败')
  } finally {
    draggingImage.value = null
    draggingSourceStudentId.value = null
  }
}


onMounted(() => {
  fetchStudentImages()
  fetchStudentList()
})
</script>

<style scoped>
.tab-actions {
  margin-bottom: 20px;
  display: flex;
  gap: 12px;
}
.images-container {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: flex-start;
}
.image-item {
  width: 160px;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 8px;
  background: #fafafa;
  cursor: grab;
}
.image-item:active {
  cursor: grabbing;
}
.image-thumb {
  width: 100%;
  height: 100px;
  object-fit: cover;
  border-radius: 4px;
  cursor: pointer;
}
.image-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}
.image-filename {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
