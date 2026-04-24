<template>
  <div class="student-manager">
    <div class="tab-actions">
      <el-button type="primary" @click="showFileImportDialog = true">
        <el-icon><Upload /></el-icon>
        从文件导入
      </el-button>
      <el-button type="success" @click="showBatchAddDialog = true">
        <el-icon><DocumentAdd /></el-icon>
        批量添加
      </el-button>
      <el-button type="info" @click="showAddExistingDialog = true">
        <el-icon><User /></el-icon>
        添加已录入学生
      </el-button>
      <el-button @click="fetchExamStudents">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>
    
    <div style="margin-bottom: 15px;">
      <el-button 
        type="danger" 
        @click="removeBatchStudents" 
        :disabled="selectedExamStudents.length === 0"
      >
        <el-icon><Delete /></el-icon>
        批量移除
      </el-button>
    </div>

    <el-table 
      ref="studentTableRef"
      :data="examStudents" 
      style="width: 100%" 
      row-key="student_id"
      @selection-change="handleExamStudentSelectionChange"
      @row-dblclick="handleExamStudentDblClick"
    >
      <el-table-column type="selection" width="55" />
      <el-table-column type="index" label="序号" width="80" />
      <el-table-column label="学号" width="120">
        <template #default="scope">
          <el-input
            v-if="editingRowId === scope.row.student_id"
            v-model="scope.row.student_number"
            @blur="saveExamStudent(scope.row)"
            @keyup.enter="saveExamStudent(scope.row)"
            size="small"
          />
          <span v-else>{{ scope.row.student_number }}</span>
        </template>
      </el-table-column>
      <el-table-column label="班级" width="150">
        <template #default="scope">
          <el-input
            v-if="editingRowId === scope.row.student_id"
            v-model="scope.row.class_name"
            @blur="saveExamStudent(scope.row)"
            @keyup.enter="saveExamStudent(scope.row)"
            size="small"
          />
          <span v-else>{{ scope.row.class_name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="姓名" width="120">
        <template #default="scope">
          <el-input
            v-if="editingRowId === scope.row.student_id"
            v-model="scope.row.name"
            @blur="saveExamStudent(scope.row)"
            @keyup.enter="saveExamStudent(scope.row)"
            size="small"
          />
          <span v-else>{{ scope.row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="联系方式">
        <template #default="scope">
          <div style="display: flex; align-items: center; justify-content: space-between;">
            <el-input
              v-if="editingRowId === scope.row.student_id"
              v-model="scope.row.contact_info"
              @blur="saveExamStudent(scope.row)"
              @keyup.enter="saveExamStudent(scope.row)"
              size="small"
              style="margin-right: 10px;"
            />
            <span v-else style="margin-right: 10px;">{{ scope.row.contact_info }}</span>
            
            <el-icon class="drag-handle" style="cursor: move; color: #909399;"><Rank /></el-icon>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <div style="margin-top: 10px; font-size: 12px; color: #909399;">
      提示：双击单元格可编辑，拖动右侧图标 <el-icon><Rank /></el-icon> 可调整顺序。
    </div>

    <!-- 添加学生对话框 -->
    <el-dialog v-model="showAddStudentDialog" title="添加学生" width="400px">
      <el-form label-width="80px">
        <el-form-item label="学生">
          <el-select v-model="selectedStudentId" placeholder="选择学生" style="width: 100%">
            <el-option
              v-for="student in allStudents"
              :key="student.student_id"
              :label="`${student.name} (${student.student_number || '无学号'})`"
              :value="student.student_id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddStudentDialog = false">取消</el-button>
        <el-button type="primary" @click="addStudentToExam">添加</el-button>
      </template>
    </el-dialog>

    <!-- 文件导入对话框 -->
    <el-dialog
      v-model="showFileImportDialog"
      title="从文件导入学生信息"
      width="600px"
      :close-on-click-modal="false"
    >
      <div style="text-align: center; padding: 40px;">
        <el-upload
          class="upload-demo"
          drag
          action=""
          :auto-upload="false"
          :on-change="handleFileChange"
          :show-file-list="true"
          accept=".xlsx,.xls,.txt,.csv"
          style="margin-bottom: 20px;"
        >
          <el-icon class="el-icon--upload"><upload-filled /></el-icon>
          <div class="el-upload__text">
            将文件拖到此处，或<em>点击上传</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              可上传Excel (.xlsx, .xls)、文本文件 (.txt, csv)
            </div>
          </template>
        </el-upload>

        <div style="margin-top: 30px;">
          <h4>支持的文件格式：</h4>
          <ul style="list-style: none; padding: 0;">
            <li>• Excel文件 (.xlsx, .xls) - 支持多列数据，列顺序：学号、班级、姓名、联系方式</li>
            <li>• 文本文件 (.txt, .csv) - 支持制表符或逗号分隔</li>
          </ul>
        </div>
      </div>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showFileImportDialog = false">取消</el-button>
          <el-button type="primary" @click="importStudentsFromFile" :disabled="!selectedFile">
            开始导入
          </el-button>
        </span>
      </template>
    </el-dialog>

    <!-- 添加已录入学生对话框 -->
    <el-dialog
      v-model="showAddExistingDialog"
      title="添加已录入学生"
      width="800px"
      @open="fetchAvailableStudents"
    >
      <div style="margin-bottom: 15px; display: flex; gap: 10px;">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索姓名/学号/班级"
          style="width: 300px;"
          @keyup.enter="searchAvailableStudents"
        >
          <template #append>
            <el-button @click="searchAvailableStudents"><el-icon><Search /></el-icon></el-button>
          </template>
        </el-input>
        <el-button @click="fetchAvailableStudents">刷新</el-button>
      </div>

      <el-table
        :data="availableStudents"
        style="width: 100%"
        height="400"
        @selection-change="handleSelectionChange"
        @row-dblclick="handleRowDblClick"
      >
        <el-table-column type="selection" width="55" />
        
        <el-table-column label="学号" width="120">
          <template #default="scope">
            <el-input
              v-if="editingRowId === scope.row.student_id"
              v-model="scope.row.student_number"
              @blur="saveStudent(scope.row)"
              @keyup.enter="saveStudent(scope.row)"
              size="small"
            />
            <span v-else>{{ scope.row.student_number }}</span>
          </template>
        </el-table-column>

        <el-table-column label="班级" width="150">
          <template #default="scope">
            <el-input
              v-if="editingRowId === scope.row.student_id"
              v-model="scope.row.class_name"
              @blur="saveStudent(scope.row)"
              @keyup.enter="saveStudent(scope.row)"
              size="small"
            />
            <span v-else>{{ scope.row.class_name }}</span>
          </template>
        </el-table-column>

        <el-table-column label="姓名" width="120">
          <template #default="scope">
            <el-input
              v-if="editingRowId === scope.row.student_id"
              v-model="scope.row.name"
              @blur="saveStudent(scope.row)"
              @keyup.enter="saveStudent(scope.row)"
              size="small"
            />
            <span v-else>{{ scope.row.name }}</span>
          </template>
        </el-table-column>

        <el-table-column label="联系方式">
          <template #default="scope">
            <el-input
              v-if="editingRowId === scope.row.student_id"
              v-model="scope.row.contact_info"
              @blur="saveStudent(scope.row)"
              @keyup.enter="saveStudent(scope.row)"
              size="small"
            />
            <span v-else>{{ scope.row.contact_info }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="80" align="center">
          <template #default="scope">
            <el-button
              type="danger"
              icon="Delete"
              circle
              size="small"
              @click.stop="deleteGlobalStudent(scope.row)"
              title="从系统中彻底删除"
            />
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top: 10px; font-size: 12px; color: #909399;">
        提示：双击单元格可编辑学生信息，按回车或点击其他区域自动保存。
      </div>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showAddExistingDialog = false">取消</el-button>
          <el-button type="primary" @click="addSelectedStudents" :disabled="selectedStudents.length === 0">
            添加选中学生 ({{ selectedStudents.length }})
          </el-button>
        </span>
      </template>
    </el-dialog>

    <!-- 批量添加学生对话框 -->
    <el-dialog
      v-model="showBatchAddDialog"
      title="批量添加学生"
      width="800px"
      :close-on-click-modal="false"
    >
      <div style="margin-bottom: 15px;">
        <el-alert
          title="请输入学生信息，每行一个学生"
          type="info"
          description="格式：学号,班级,姓名,联系方式 (班级和联系方式为可选，用逗号分隔)"
          :closable="false"
        />
      </div>

      <el-input
        v-model="batchAddText"
        type="textarea"
        :rows="8"
        placeholder="示例：&#10;001,一班,张三,13800138000&#10;002,二班,李四,&#10;003,一班,王五,13900139000&#10;004,,赵六"
      />

      <div style="margin-top: 15px;">
        <h4>输入格式说明：</h4>
        <ul style="list-style: none; padding: 0; font-size: 13px; color: #666;">
          <li>• 每行输入一个学生信息</li>
          <li>• 使用逗号分隔：学号,班级,姓名,联系方式</li>
          <li>• 班级和联系方式为可选项，但逗号位置需保留（如：004,,赵六）</li>
          <li>• 必须包含学号和姓名</li>
        </ul>
      </div>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showBatchAddDialog = false">取消</el-button>
          <el-button type="primary" @click="batchAddStudents" :disabled="!batchAddText.trim()">
            添加学生
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch, defineProps, defineEmits } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, DocumentAdd, UploadFilled, Search, User, Refresh, Delete, Rank } from '@element-plus/icons-vue'
import axios from 'axios'
 
const props = defineProps({
  examId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['update:students'])

const examStudents = ref([])
const allStudents = ref([])
const availableStudents = ref([])
const selectedStudents = ref([])
const selectedExamStudents = ref([])
const editingRowId = ref(null)
const studentTableRef = ref(null)

// 对话框控制
const showAddStudentDialog = ref(false)
const showAddExistingDialog = ref(false)
const showFileImportDialog = ref(false)
const showBatchAddDialog = ref(false)

// 表单数据
const selectedStudentId = ref('')
const selectedFile = ref(null)
const batchAddText = ref('')
const searchKeyword = ref('')

// 获取考试学生
const fetchExamStudents = async () => {
  try {
    const response = await axios.get(`http://localhost:8001/api/exams/${props.examId}/students`)
    examStudents.value = response.data.data || []
    emit('update:students', examStudents.value)
  } catch (error) {
    console.error('获取考试学生失败:', error)
    ElMessage.error('获取考试学生失败')
  }
}

// 获取所有学生
const fetchAllStudents = async () => {
  try {
    const response = await axios.get('http://localhost:8001/api/students')
    allStudents.value = response.data.data || []
  } catch (error) {
    console.error('获取所有学生失败:', error)
  }
}

// 获取未分配到该考试的学生
const fetchAvailableStudents = async () => {
  try {
    const params = {}
    if (searchKeyword.value) {
      params.search = searchKeyword.value
    }
    const response = await axios.get(`http://localhost:8001/api/exams/${props.examId}/available-students`, { params })
    availableStudents.value = response.data.data || []
  } catch (error) {
    console.error('获取可用学生失败:', error)
    ElMessage.error('获取可用学生失败')
  }
}

const searchAvailableStudents = () => {
  fetchAvailableStudents()
}

const handleSelectionChange = (selection) => {
  selectedStudents.value = selection
}

const handleRowDblClick = (row) => {
  editingRowId.value = row.student_id
}

const handleExamStudentSelectionChange = (selection) => {
  selectedExamStudents.value = selection
}

const handleExamStudentDblClick = (row) => {
  editingRowId.value = row.student_id
}

const handleFileChange = (file) => {
  selectedFile.value = file.raw
}

// 保存学生信息
const saveStudent = async (student) => {
  if (editingRowId.value !== student.student_id) return
  
  if (!student.name) {
    ElMessage.error('姓名不能为空')
    return
  }
  if (!student.student_number) {
    ElMessage.error('学号不能为空')
    return
  }

  try {
    const response = await axios.put(`http://localhost:8001/api/students/${student.student_id}`, {
      name: student.name,
      student_number: student.student_number,
      class_name: student.class_name,
      contact_info: student.contact_info
    })

    if (response.data.code === 1) {
      ElMessage.success('更新成功')
      editingRowId.value = null
    } else {
      ElMessage.error(response.data.msg || '更新失败')
    }
  } catch (error) {
    console.error('更新学生失败:', error)
    if (error.response && error.response.data && error.response.data.detail) {
       ElMessage.error(error.response.data.detail)
    } else {
       ElMessage.error('更新失败，可能是学号已存在')
    }
    fetchAvailableStudents()
  }
}

// 保存考试学生信息
const saveExamStudent = async (student) => {
  if (editingRowId.value !== student.student_id) return
  
  if (!student.name) {
    ElMessage.error('姓名不能为空')
    return
  }
  if (!student.student_number) {
    ElMessage.error('学号不能为空')
    return
  }

  try {
    const response = await axios.put(`http://localhost:8001/api/students/${student.student_id}`, {
      name: student.name,
      student_number: student.student_number,
      class_name: student.class_name,
      contact_info: student.contact_info
    })

    if (response.data.code === 1) {
      ElMessage.success('更新成功')
      editingRowId.value = null
    } else {
      ElMessage.error(response.data.msg || '更新失败')
    }
  } catch (error) {
    console.error('更新学生失败:', error)
    if (error.response && error.response.data && error.response.data.detail) {
       ElMessage.error(error.response.data.detail)
    } else {
       ElMessage.error('更新失败，可能是学号已存在')
    }
    fetchExamStudents()
  }
}

// 全局删除学生
const deleteGlobalStudent = async (student) => {
  try {
    const confirmed = await ElMessageBox.confirm(
      '彻底删除确认',
      `确定要从系统中彻底删除学生 "${student.name}" (${student.student_number}) 吗？
警告：此操作不可恢复！将同时删除该学生在所有考试中的关联信息、答卷图片和成绩数据。`,
      {
        confirmButtonText: '确定彻底删除',
        cancelButtonText: '取消',
        type: 'error',
        confirmButtonClass: 'el-button--danger'
      }
    )

    if (!confirmed) return

    const response = await axios.delete(`http://localhost:8001/api/students/${student.student_id}`)

    if (response.data.code === 1) {
      ElMessage.success('删除成功')
      await fetchAvailableStudents()
    } else {
      ElMessage.error(response.data.msg || '删除失败')
    }
  } catch (error) {
    if (error !== 'cancel') {
        console.error('删除学生失败:', error)
        ElMessage.error('删除学生失败')
    }
  }
}

// 添加选中的学生到考试
const addSelectedStudents = async () => {
  if (selectedStudents.value.length === 0) {
    ElMessage.warning('请选择要添加的学生')
    return
  }

  try {
    const studentIds = selectedStudents.value.map(student => student.student_id)
    const response = await axios.post(`http://localhost:8001/api/exams/${props.examId}/add-existing-students`, studentIds, {
      headers: { 'Content-Type': 'application/json' }
    })

    if (response.data.code === 1) {
      ElMessage.success(`成功添加 ${response.data.data.added_count} 个学生`)
      showAddExistingDialog.value = false
      selectedStudents.value = []
      await fetchExamStudents()
    } else {
      ElMessage.error(response.data.msg || '添加失败')
    }
  } catch (error) {
    console.error('添加学生失败:', error)
    ElMessage.error('添加学生失败')
  }
}

// 添加学生到考试
const addStudentToExam = async () => {
  try {
    const response = await axios.post(`http://localhost:8001/api/exams/${props.examId}/students`, selectedStudentId.value, {
      headers: { 'Content-Type': 'application/json' }
    })

    if (response.data.code === 1) {
      ElMessage.success('添加成功')
      showAddStudentDialog.value = false
      selectedStudentId.value = ''
      await fetchExamStudents()
    } else {
      ElMessage.error(response.data.msg || '添加失败')
    }
  } catch (error) {
    console.error('添加学生失败:', error)
    ElMessage.error('添加学生失败')
  }
}

// 批量移除学生
const removeBatchStudents = async () => {
  if (selectedExamStudents.value.length === 0) return

  try {
    const confirmed = await ElMessageBox.confirm(
      '移除确认',
      `确定要从本次考试中移除选中的 ${selectedExamStudents.value.length} 名学生吗？`,
      {
        confirmButtonText: '确定移除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    if (!confirmed) return

    const studentIds = selectedExamStudents.value.map(s => s.student_id)
    const response = await axios.post(`http://localhost:8001/api/exams/${props.examId}/students/remove-batch`, studentIds, {
      headers: { 'Content-Type': 'application/json' }
    })

    if (response.data.code === 1) {
      ElMessage.success(`成功移除 ${response.data.data.removed_count} 名学生`)
      selectedExamStudents.value = []
      await fetchExamStudents()
    } else {
      ElMessage.error(response.data.msg || '移除失败')
    }
  } catch (error) {
    if (error !== 'cancel') {
        console.error('批量移除学生失败:', error)
        ElMessage.error('批量移除学生失败')
    }
  }
}

// 批量添加学生
const batchAddStudents = async () => {
  if (!batchAddText.value.trim()) {
    ElMessage.error('请输入学生信息')
    return
  }

  try {
    const lines = batchAddText.value.trim().split('\n')
    const students = []

    lines.forEach(line => {
      const parts = line.split(',').map(part => part.trim())
      if (parts.length >= 1) {
        students.push({
          student_number: parts[0],
          class_name: parts[1] || '',
          name: parts[2] || '',
          contact_info: parts[3] || ''
        })
      }
    })

    if (students.length === 0) {
      ElMessage.error('未找到有效的学生信息')
      return
    }

    ElMessage.info('正在批量添加学生，请稍候...')
    const response = await axios.post(`http://localhost:8001/api/exams/${props.examId}/batch-add-students`, {
      students: students
    })

    if (response.data.code === 1) {
      const { added_count, errors } = response.data.data
      
      if (errors && errors.length > 0) {
        const prefix = added_count > 0 ? `部分添加成功` : `批量添加失败`
        const errorMsg = `${prefix}：成功 ${added_count} 人，失败 ${errors.length} 人。原因：${errors.join('; ')}`
        
        ElMessage.warning({
          message: errorMsg,
          duration: 5000,
          showClose: true
        })
      } else if (added_count === 0) {
        ElMessage.warning('未添加任何学生（可能是列表为空）')
      } else {
        ElMessage.success(`批量添加成功！共添加 ${added_count} 个学生`)
      }
      
      showBatchAddDialog.value = false
      batchAddText.value = ''
      await fetchExamStudents()
    } else {
      ElMessage.error(response.data.msg || '批量添加失败')
    }
  } catch (error) {
    console.error('批量添加失败:', error)
    ElMessage.error('批量添加失败')
  }
}

// 从文件导入学生
const importStudentsFromFile = async () => {
  if (!selectedFile.value) {
    ElMessage.error('请选择文件')
    return
  }

  const formData = new FormData()
  formData.append('file', selectedFile.value)

  try {
    ElMessage.info('正在导入文件，请稍候...')
    const response = await axios.post(`http://localhost:8001/api/exams/${props.examId}/import-students`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })

    if (response.data.code === 1) {
      ElMessage.success(`文件导入成功！共导入 ${response.data.data.imported_count} 个学生`)
      showFileImportDialog.value = false
      selectedFile.value = null
      await fetchExamStudents()
      emit('refresh')   // 新增
    } else {
      ElMessage.error(response.data.msg || '文件导入失败')
    }
  } catch (error) {
    console.error('文件导入失败:', error)
    ElMessage.error('文件导入失败')
  }
}

// 拖拽排序相关
const reorderExamStudents = async () => {
  try {
    const studentIds = examStudents.value.map(s => s.student_id)
    await axios.post(`http://localhost:8001/api/exams/${props.examId}/students/reorder`, studentIds)
  } catch (error) {
    console.error('更新排序失败:', error)
    ElMessage.error('更新排序失败')
  }
}

const ensureRowsDraggable = () => {
  if (!studentTableRef.value) return
  const trs = studentTableRef.value.$el.querySelectorAll('.el-table__body-wrapper tbody tr')
  trs.forEach(tr => {
    tr.setAttribute('draggable', 'true')
  })
}

const initDragAndDrop = () => {
  if (!studentTableRef.value) return

  const tbody = studentTableRef.value.$el.querySelector('.el-table__body-wrapper tbody')
  if (!tbody) return

  if (tbody.getAttribute('data-dnd-initialized')) return
  tbody.setAttribute('data-dnd-initialized', 'true')

  let draggingIndex = -1

  tbody.addEventListener('dragstart', (e) => {
    const tr = e.target.closest('tr')
    if (!tr) return
    
    draggingIndex = tr.sectionRowIndex
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', draggingIndex)
    tr.classList.add('dragging')
  })

  tbody.addEventListener('dragend', (e) => {
    const tr = e.target.closest('tr')
    if (tr) tr.classList.remove('dragging')
    draggingIndex = -1
  })

  tbody.addEventListener('dragover', (e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  })

  tbody.addEventListener('dragenter', (e) => {
    const destTr = e.target.closest('tr')
    if (!destTr || draggingIndex === -1 || destTr.sectionRowIndex === draggingIndex) return
    
    const destIndex = destTr.sectionRowIndex
    
    const items = [...examStudents.value]
    const movedItem = items[draggingIndex]
    items.splice(draggingIndex, 1)
    items.splice(destIndex, 0, movedItem)
    examStudents.value = items
    
    draggingIndex = destIndex
  })

  tbody.addEventListener('drop', async (e) => {
    e.preventDefault()
    if (draggingIndex !== -1) {
      await reorderExamStudents()
    }
  })
}

watch(examStudents, () => {
  nextTick(() => {
    ensureRowsDraggable()
  })
}, { deep: true })

onMounted(async () => {
  await fetchExamStudents()
  await fetchAllStudents()
  
  nextTick(() => {
    initDragAndDrop()
    ensureRowsDraggable()
  })
})
</script>

<style scoped>
.tab-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}
:deep(.el-table__body tr.dragging) {
  opacity: 0.5;
  background: #f0f9eb;
}
.drag-handle {
  cursor: move;
  margin-left: 8px;
}
</style>
