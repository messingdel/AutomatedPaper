<template>
  <div class="ai-grading-container">
    <div class="ai-grading-header">
      <h3>AI阅卷控制台</h3>
      <p>使用人工智能对学生的答卷进行自动评分和分析</p>
    </div>

    <div class="ai-grading-actions">
      <el-button
        type="success"
        size="large"
        @click="triggerAIGrading"
        :loading="aiGradingInProgress"
      >
        <el-icon><Cpu /></el-icon>
        开始AI阅卷
      </el-button>
      <el-button @click="refreshAll">
        <el-icon><Refresh /></el-icon>
        刷新状态
      </el-button>
      <el-button type="info" @click="exportObjectiveAnswers">
        <el-icon><Download /></el-icon>
        导出客观题答案
      </el-button>
    </div>

    <div class="ai-grading-status" v-if="aiGradingInProgress">
      <el-progress :percentage="aiGradingProgress" :status="aiGradingStatus" />
      <p>{{ aiGradingMessage }}</p>
    </div>

    <div class="ai-grading-info" v-if="!aiGradingInProgress">
      <el-card>
        <template #header>
          <span>阅卷统计</span>
        </template>
        <div class="stats-grid">
          <div class="stat-item">
            <div class="stat-value">{{ ungradedCount }}</div>
            <div class="stat-label">待阅卷</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ gradedCount }}</div>
            <div class="stat-label">已完成</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ totalStudents }}</div>
            <div class="stat-label">总学生数</div>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 学生答题详情表格 -->
    <el-card style="margin-top: 20px">
      <template #header>
        <span>学生答题详情</span>
      </template>
      <el-table :data="studentScoreList" border v-loading="loadingScores">
        <!-- 新增序号列 -->
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column prop="name" label="姓名" width="120" />
        <el-table-column prop="student_number" label="学号" width="150" />
        <el-table-column label="总分" width="100">
          <template #default="{ row }">
            {{ row.total_score !== null ? row.total_score : '未评分' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button type="primary" link @click="showDetail(row)">查看详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 详情对话框 -->
    <el-dialog
      v-model="detailVisible"
      :title="`${currentStudent?.name} 的答题详情`"
      width="850px"
      @closed="closeDetail"
    >
      <el-table :data="currentStudent?.question_scores || []" border>
        <el-table-column prop="question_order" label="题号" width="80" />
        <el-table-column label="学生答案" min-width="250" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.student_answer === null">（题目缺失）</span>
            <span v-else>{{ row.student_answer || '（未识别）' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="得分" width="220">
          <template #default="{ row }">
            <div v-if="row.score === null" style="display: flex; align-items: center; gap: 8px;">
              <el-tag type="info" size="small">未评分</el-tag>
              <el-button size="small" type="primary" @click="startRating(row)">评分</el-button>
            </div>
            <div v-else style="display: flex; align-items: center; gap: 8px;">
              <el-input-number
                v-model="row.score"
                :min="0"
                :max="row.max_score || 100"
                size="small"
                controls-position="right"
                :disabled="updatingScores.has(row.question_id)"
                style="width: 120px"
              />
              <el-button
                type="primary"
                size="small"
                :loading="updatingScores.has(row.question_id)"
                @click="updateScore(row)"
              >保存</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Cpu, Refresh, Download } from '@element-plus/icons-vue'
import axios from 'axios'

const props = defineProps({
  examId: {
    type: [String, Number],
    required: true
  },
  scores: {
    type: Object,
    default: () => ({ total: 0, graded: 0 })
  },
  totalStudents: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['refresh'])

// 阅卷相关
const aiGradingInProgress = ref(false)
const aiGradingProgress = ref(0)
const aiGradingStatus = ref('success')
const aiGradingMessage = ref('')

// 学生成绩列表
const studentScoreList = ref([])
const loadingScores = ref(false)
const detailVisible = ref(false)
const currentStudent = ref(null)
const updatingScores = ref(new Set())

// 考试总分（用于校验）
const examTotalScore = ref(null)

const ungradedCount = computed(() => props.scores.total - props.scores.graded)
const gradedCount = computed(() => props.scores.graded)

// 获取学生成绩列表
const fetchStudentScores = async () => {
  loadingScores.value = true
  try {
    const res = await axios.get(`/api/exams/${props.examId}/scores`)
    if (res.data.code === 1) {
      const data = res.data.data
      examTotalScore.value = data.exam_info?.total_score ?? null
      // 直接使用后端数据，不再添加识别状态标记
      studentScoreList.value = data.students || []
    } else {
      ElMessage.error(res.data.msg || '获取成绩失败')
    }
  } catch (error) {
    console.error('获取成绩失败:', error)
    ElMessage.error('获取成绩失败')
  } finally {
    loadingScores.value = false
  }
}

// 显示详情
const showDetail = (student) => {
  currentStudent.value = student
  detailVisible.value = true
}

const closeDetail = () => {
  currentStudent.value = null
  updatingScores.value.clear()
}

// 更新单题分数
const updateScore = async (question) => {
  const studentId = currentStudent.value.student_id
  const questionId = question.question_id
  const newScore = question.score

  if (newScore === undefined || newScore === null) {
    ElMessage.error('请输入有效分数')
    return
  }

  let newTotal = 0
  for (const q of currentStudent.value.question_scores) {
    if (q.question_id === questionId) {
      newTotal += newScore
    } else {
      newTotal += (q.score || 0)
    }
  }
  if (examTotalScore.value !== null && newTotal > examTotalScore.value) {
    ElMessage.error(`总分不能超过考试总分 ${examTotalScore.value} 分`)
    return
  }

  updatingScores.value.add(questionId)
  try {
    const res = await axios.put(`/api/exams/${props.examId}/scores/${studentId}/${questionId}`, {
      score: newScore
    })
    if (res.data.code === 1) {
      ElMessage.success('分数已更新')
      await fetchStudentScores()
      emit('refresh')
      const updatedStudent = studentScoreList.value.find(s => s.student_id === studentId)
      if (updatedStudent) currentStudent.value = updatedStudent
    } else {
      ElMessage.error(res.data.msg || '更新失败')
    }
  } catch (error) {
    console.error('更新分数失败:', error)
    ElMessage.error('更新分数失败')
  } finally {
    updatingScores.value.delete(questionId)
  }
}

// 为未评分题目手动评分
const startRating = async (question) => {
  try {
    const { value } = await ElMessageBox.prompt('请输入分数', '评分', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputPattern: /^(\d+)(\.\d+)?$/,
      inputErrorMessage: '请输入数字分数'
    })
    const newScore = parseFloat(value)
    if (isNaN(newScore)) throw new Error('无效分数')
    question.score = newScore
    await updateScore(question)
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error('评分失败')
    }
  }
}

// 开始AI阅卷
const triggerAIGrading = async () => {
  try {
    aiGradingInProgress.value = true
    aiGradingMessage.value = '正在启动阅卷任务...'
    aiGradingProgress.value = 0

    const startRes = await axios.post(`/api/exams/${props.examId}/grade`)
    if (startRes.data.code !== 1) throw new Error(startRes.data.msg || '启动失败')
    const { job_id } = startRes.data.data

    aiGradingMessage.value = '阅卷任务已启动，正在处理...'
    let finished = false
    while (!finished) {
      await new Promise(resolve => setTimeout(resolve, 2000))
      const statusRes = await axios.get(`/api/grading/jobs/${job_id}`)
      if (statusRes.data.code !== 1) throw new Error(statusRes.data.msg)
      const { status, total_students, processed_students } = statusRes.data.data

      if (total_students > 0) {
        aiGradingProgress.value = Math.floor((processed_students / total_students) * 100)
      }
      if (status === 'completed') {
        finished = true
        aiGradingMessage.value = '阅卷完成'
        ElMessage.success(`阅卷完成，共处理 ${total_students} 名学生`)
        await fetchStudentScores()
        emit('refresh')
        break
      } else if (status === 'failed') {
        throw new Error('阅卷任务失败')
      }
    }
  } catch (error) {
    console.error(error)
    aiGradingStatus.value = 'exception'
    aiGradingMessage.value = error.message || 'AI阅卷失败'
    ElMessage.error(error.message || 'AI阅卷失败')
  } finally {
    aiGradingInProgress.value = false
    setTimeout(() => {
      aiGradingProgress.value = 0
    }, 2000)
  }
}

// 手动刷新
const refreshAll = () => {
  emit('refresh')
  fetchStudentScores()
}

// 导出选择题和填空题答案
const exportObjectiveAnswers = async () => {
  try {
    const response = await axios.get(`/api/exams/${props.examId}/export-objective`, {
      responseType: 'blob'
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `exam_${props.examId}_objective_answers.xlsx`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (error) {
    console.error('导出失败:', error)
    ElMessage.error('导出失败')
  }
}

onMounted(() => {
  fetchStudentScores()
})
</script>

<style scoped>
.ai-grading-container {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.ai-grading-header {
  text-align: center;
}
.ai-grading-header h3 {
  margin: 0 0 8px 0;
  color: #374151;
  font-size: 1.5rem;
  font-weight: 600;
}
.ai-grading-header p {
  margin: 0;
  color: #6b7280;
  font-size: 1rem;
}
.ai-grading-actions {
  display: flex;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
}
.ai-grading-status {
  text-align: center;
  padding: 20px;
  background: #f9fafb;
  border-radius: 8px;
}
.ai-grading-status p {
  margin: 12px 0 0 0;
  color: #374151;
  font-weight: 500;
}
.ai-grading-info {
  margin-top: 24px;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  margin-top: 16px;
}
.stat-item {
  text-align: center;
  padding: 20px;
  background: #f9fafb;
  border-radius: 8px;
  transition: all 0.2s;
}
.stat-item:hover {
  background: #f3f4f6;
  transform: translateY(-2px);
}
.stat-value {
  font-size: 2rem;
  font-weight: bold;
  color: #3b82f6;
  margin-bottom: 8px;
}
.stat-label {
  font-size: 0.9rem;
  color: #6b7280;
  font-weight: 500;
}
</style>