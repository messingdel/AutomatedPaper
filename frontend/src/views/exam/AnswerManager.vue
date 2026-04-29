<template>
  <div class="answer-manager">
    <div class="tab-actions">
      <el-button type="primary" @click="openUploadDialog">上传图片</el-button>
      <el-button @click="fetchStudentImages">刷新</el-button>
      <el-button type="success" @click="handleImportFolder">导入文件夹</el-button>
    </div>

    <!-- 学生表格（每个学生一行，展示其多张图片） -->
    <el-table :data="studentList" style="width: 100%" row-key="student_id">
      <!-- 新增序号列 -->
      <el-table-column type="index" label="序号" width="60" />
      <el-table-column prop="student_number" label="学号" width="120" />
      <el-table-column prop="name" label="姓名" width="100" />
      <el-table-column prop="class" label="班级" width="120" />
      <el-table-column label="答题卡图片" min-width="400">
        <template #default="{ row }">
          <div class="images-container">
            <div
              v-for="img in row.images"
              :key="img.id"
              class="image-item"
            >
              <el-image
                :src="getImageUrl(img)"
                fit="cover"
                class="image-thumb"
                :preview-src-list="[getImageUrl(img)]"
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
    type: [String, Number],
    required: true
  },
  students: {
    type: Array,
    default: () => []
  },
  imagesPerStudent: {
    type: Number,
    default: 4
  }
})

// 学生列表（每个学生包含其图片数组）
const studentList = ref([])

// 上传对话框相关
const showUploadDialog = ref(false)
const uploadStudentId = ref(null)
const uploadFileList = ref([])

// 上传文件夹状态
const folderUploading = ref(false)

// 获取图片URL（优先使用预处理后的图片）
const getImageUrl = (img) => {
  const filePath = img.processed_file_path || img.file_path
  let relative = filePath
  if (relative.startsWith('./')) relative = relative.slice(2)
  if (relative.startsWith('uploads/')) relative = relative.slice(8)
  return `http://localhost:8001/uploads/${relative}`
}

// 获取考试所有学生的图片并组装数据
const fetchStudentImages = async () => {
  try {
    const studentsRes = await axios.get(`http://localhost:8001/api/exams/${props.examId}/students`)
    if (studentsRes.data.code !== 1) {
      ElMessage.error('获取学生列表失败')
      return
    }
    const students = studentsRes.data.data

    const imagesRes = await axios.get(`http://localhost:8001/api/exams/${props.examId}/images`)
    if (imagesRes.data.code !== 1) {
      ElMessage.error('获取图片列表失败')
      return
    }
    const images = imagesRes.data.data

    const imgMap = new Map()
    for (const img of images) {
      const sid = img.student.student_id
      if (!imgMap.has(sid)) imgMap.set(sid, [])
      imgMap.get(sid).push(img)
    }

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

// 上传图片（单学生多张）
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
      await fetchStudentImages()
    }
  } catch (error) {
    console.error('更新顺序失败:', error)
    ElMessage.error('更新顺序失败')
    await fetchStudentImages()
  }
}

// 为某个学生单独添加图片
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

// 获取学生列表（内部用）
const fetchStudentList = async () => {
  try {
    const res = await axios.get(`/api/exams/${props.examId}/students`)
    if (res.data.code === 1) {
      // 仅用于学生列表备胎，一般不直接使用
    }
  } catch (error) {
    console.error('获取学生列表失败', error)
  }
}

// 处理文件夹导入（使用 imagesPerStudent）
const handleImportFolder = async () => {
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

    const totalStudents = students.length
    const imagesPerStudent = props.imagesPerStudent   // 使用动态设置
    const requiredImages = totalStudents * imagesPerStudent

    if (imageFiles.length < requiredImages) {
      ElMessage.error(`图片数量不足，需要 ${requiredImages} 张，实际 ${imageFiles.length} 张`)
      return
    }

    const groups = []
    for (let i = 0; i < totalStudents; i++) {
      const student = students[i]
      const startIdx = i * imagesPerStudent
      const studentImages = imageFiles.slice(startIdx, startIdx + imagesPerStudent)
      groups.push({ studentId: student.student_id, files: studentImages })
    }

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
          `http://localhost:8001/api/exams/${props.examId}/images`,
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
    await fetchStudentImages()
  }

  input.click()
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
  border-radius: 8px;
  padding: 8px;
  background: #fafafa;
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