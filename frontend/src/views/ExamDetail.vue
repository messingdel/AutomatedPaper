<template>
  <div class="exam-detail-container">
    <div class="header">
      <el-button @click="goBack" type="text">
        <el-icon><ArrowLeft /></el-icon>
        返回
      </el-button>
      <h1 v-if="exam">{{ exam.exam_name }}</h1>
    </div>

    <div v-if="!exam" class="loading">
      <el-skeleton :rows="6" animated />
    </div>

    <div v-else class="content">
      <!-- 考试信息卡片 -->
      <el-card class="exam-info-card">
        <template #header>
          <span>考试信息</span>
        </template>
        <div class="exam-info-layout">
          <!-- 第一行：描述 -->
          <div class="info-row first-row">
            <label>描述：</label>
            <span>{{ exam.description || '暂无描述' }}</span>
          </div>

          <!-- 第二行：开考时间、考试人数、题目数量、卷面总分 -->
          <div class="info-row second-row">
            <div class="info-item">
              <label>开考时间：</label>
              <span>{{ formatExamDate(exam.exam_date) || '未设置' }}</span>
            </div>
            <div class="info-item">
              <label>考试人数：</label>
              <span>{{ currentStudentCount }} 人</span>
            </div>
            <div class="info-item">
              <label>题目数量：</label>
              <span>{{ currentQuestionCount }} 道</span>
            </div>
            <div class="info-item">
              <label>卷面总分：</label>
              <span>{{ currentTotalScore }} 分</span>
            </div>
          </div>
        </div>
      </el-card>

      <!-- 功能标签页 -->
      <el-card class="main-card">
        <el-tabs v-model="activeTab" type="card">
          <!-- 学生信息 -->
          <el-tab-pane label="学生信息" name="students">
            <div class="tab-content">
              <StudentManager 
                :exam-id="examId" 
                @update:students="handleStudentsUpdate" 
              />
            </div>
          </el-tab-pane>

          <!-- 参考答案和题目信息 -->
          <el-tab-pane label="参考答案和题目信息" name="questions">
            <div class="tab-content">
              <QuestionManager 
                :exam-id="examId" 
                @update:questions="handleQuestionsUpdate" 
              />
            </div>
          </el-tab-pane>

          <!-- 学生作答管理-->
          <el-tab-pane label="学生作答管理" name="images">
            <div class="tab-content">
              <AnswerManager 
                :exam-id="examId" 
                :students="examStudents" 
              />
            </div>
          </el-tab-pane>
          

          <!-- AI阅卷 -->
          <el-tab-pane label="AI阅卷" name="ai-grading">
            <div class="tab-content">
              <AIGradingConsole 
                :exam-id="examId" 
                :scores="gradingStats"
                :total-students="examStudents.length"
                @refresh="fetchGradingStas"
              />
            </div>
          </el-tab-pane>
          

          <!-- 成绩管理 -->
          <el-tab-pane label="成绩管理" name="scores">
            <div class="tab-content">
              <ScoreManager 
                :scores="scoreList"
                :exam-id="examId" 
                @refresh="fetchScores"
              />
            </div>
          </el-tab-pane>
          
        </el-tabs>
      </el-card>
    </div>

    <!-- 添加学生对话框 -->
    <el-dialog v-model="showAddStudentDialog" title="添加学生" width="400px">
      <el-form :model="newStudent" label-width="80px">
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





  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, computed } from 'vue'
import StudentManager from './exam/StudentManager.vue'
import QuestionManager from './exam/QuestionManager.vue'
import AnswerManager from './exam/AnswerManager.vue'
import AIGradingConsole from './exam/AIGradingConsole.vue'
import ScoreManager from './exam/ScoreManager.vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Upload, DocumentAdd, UploadFilled, Search, User, Refresh, Cpu, Delete, Rank } from '@element-plus/icons-vue'
import axios from 'axios'

const route = useRoute()
const router = useRouter()
const examId = route.params.exam_id

const goBack = () => {
  router.push('/home')
}

const exam = ref(null)
const activeTab = ref('students')
const examStudents = ref([])
const questions = ref([])
// 阅卷进度统计（对象）
const gradingStats = ref({ total: 0, graded: 0 })

// 成绩列表（数组）
const scoreList = ref([])

const showAddStudentDialog = ref(false)
const selectedStudentId = ref('')
const newStudent = ref({})
const allStudents = ref([])

// Computed properties for exam statistics
const currentStudentCount = computed(() => {
  return examStudents.value.length
})

const currentQuestionCount = computed(() => {
  return questions.value.length
})

const currentTotalScore = computed(() => {
  return questions.value.reduce((sum, q) => {
    return sum + (Number(q.score) || 0)
  }, 0)
})

// 获取考试信息
const fetchExam = async () => {
  try {
    const response = await axios.get(`http://localhost:8001/api/exams`)
    const exams = response.data.data || []
    exam.value = exams.find(e => e.exam_id == examId)
  } catch (error) {
    console.error('获取考试信息失败:', error)
    ElMessage.error('获取考试信息失败')
  }
}

const handleStudentsUpdate = (students) => {
  examStudents.value = students
}

// 获取阅卷进度统计
const fetchGradingStats = async () => {
  try {
    const res = await axios.get(`/api/exams/${examId}/grading-progress`)
    if (res.data.code === 1) {
      gradingStats.value = res.data.data
    }
  } catch (error) {
    console.error('获取阅卷统计失败', error)
  }
}


// 处理题目更新
const handleQuestionsUpdate = (newQuestions) => {
  questions.value = newQuestions
}


// 获取成绩列表
const fetchScores = async () => {
  try {
    const response = await axios.get(`http://localhost:8001/api/exams/${examId}/scores`)
    if (response.data.code === 1) {
      scoreList.value = response.data.data.students || []
    } else {
      scoreList.value = []
    }
  } catch (error) {
    console.error('获取成绩列表失败:', error)
    scoreList.value = []
  }
}




// 格式化考试日期
const formatExamDate = (dateStr) => {
  if (!dateStr) return null
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 获取题目数量文本
const getQuestionCountText = () => {
  if (!exam.value) return '未上传参考答案文档'

  const totalQuestions = exam.value.total_questions
  const status = exam.value.status

  if (status === 'processing' || status === 'error') {
    return '未正确识别'
  } else if (totalQuestions != null && totalQuestions > 0) {
    return `${totalQuestions} 道`
  } else {
    return '未上传参考答案文档'
  }
}

// 获取卷面总分文本
const getTotalScoreText = () => {
  if (!exam.value) return '未上传参考答案文档'

  const totalScore = exam.value.total_score
  const status = exam.value.status

  if (status === 'processing' || status === 'error') {
    return '未正确识别'
  } else if (totalScore != null && totalScore > 0) {
    return `${totalScore} 分`
  } else {
    return '未上传参考答案文档'
  }
}

// 获取参考答案状态
const getReferenceAnswerStatus = () => {
  if (!exam.value) return 'not_uploaded'

  const status = exam.value.status
  const hasQuestions = questions.value && questions.value.length > 0

  if (status === 'processing') {
    return 'processing'
  } else if (status === 'error' || (status !== 'graded' && !hasQuestions)) {
    return 'error'
  } else if (hasQuestions || status === 'graded') {
    return 'uploaded'
  } else {
    return 'not_uploaded'
  }
}

// 获取参考答案文本
const getReferenceAnswerText = () => {
  const status = getReferenceAnswerStatus()
  const statusMap = {
    'not_uploaded': '未上传',
    'processing': '处理中',
    'uploaded': '已上传',
    'error': '未正确识别'
  }
  return statusMap[status] || '未上传'
}

// 获取参考答案标签类型
const getReferenceAnswerType = () => {
  const status = getReferenceAnswerStatus()
  const typeMap = {
    'not_uploaded': 'info',
    'processing': 'warning',
    'uploaded': 'success',
    'error': 'danger'
  }
  return typeMap[status] || 'info'
}

// 获取参考答案按钮文本
const getReferenceAnswerButtonText = () => {
  const status = getReferenceAnswerStatus()
  const textMap = {
    'not_uploaded': '上传',
    'processing': '处理中...',
    'uploaded': '已上传',
    'error': '重新上传'
  }
  return textMap[status] || '上传'
}

// 显示参考答案上传对话框
const showReferenceAnswerUpload = () => {
  // 激活题目管理标签页
  activeTab.value = 'questions'
  // 可以在这里添加其他逻辑，比如显示上传提示等
  ElMessage.info('请在"题目管理"标签页中上传参考答案文档')
}



// 文件导入相关函数
const handleFileChange = (file) => {
  selectedFile.value = file.raw
}



// 导出成绩函数
const exportScores = () => {
  ElMessage.info('成绩导出功能开发中...')
}

// 在 onMounted 中调用
onMounted(() => {
  fetchExam()
  fetchGradingStats()   // 更新 gradingStats
  fetchScores()         // 更新 scoreList
})
</script>

<style scoped>
/* Add styles for drag and drop visual feedback */
:deep(.el-table__body tr.dragging) {
  opacity: 0.5;
  background: #f0f9eb;
}
:deep(.el-table__body tr.drag-over) {
  border-top: 2px solid #409eff;
}
.drag-handle {
  cursor: move;
  margin-left: 8px;
}
/* Existing styles... */
.exam-detail-container {
  padding: 24px;
  background: #f5f7fa;
  min-height: 100vh;
}

.header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.header h1 {
  color: #2c3e50;
  margin: 0;
}

.loading {
  background: white;
  padding: 24px;
  border-radius: 8px;
}

.content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.exam-info-card {
  margin-bottom: 24px;
}

.exam-info-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.info-row.first-row {
  font-size: 16px;
  font-weight: 500;
}

.info-row.second-row {
  justify-content: space-between;
}

.info-row.third-row {
  justify-content: space-between;
  align-items: center;
}

.info-row .info-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.reference-answer-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.info-item label {
  font-weight: bold;
  color: #606266;
  min-width: 80px;
}

.main-card {
  flex: 1;
}

.tab-content {
  padding: 20px 0;
}

.tab-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}



.truncate-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
</style>
