<template>
  <div class="score-manager">
    <el-card>
      <template #header>
        <div class="header-actions">
          <span>成绩列表</span>
          <el-button type="primary" @click="exportExcel">导出Excel</el-button>
        </div>
      </template>

      <el-table :data="studentList" border v-loading="loading">
        <el-table-column prop="name" label="姓名" width="120" />
        <el-table-column label="得分" width="100">
          <template #default="{ row }">
            {{ row.total_score !== null ? row.total_score : '未评分' }}
          </template>
        </el-table-column>
        <el-table-column label="满分" width="100">
          <template #default>
            {{ examInfo?.total_score || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="阅卷状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.grading_status === 'completed' ? 'success' : 'info'">
              {{ row.grading_status === 'completed' ? '已完成' : '未完成' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="阅卷时间" width="180">
          <template #default="{ row }">
            {{ row.graded_at ? formatDate(row.graded_at) : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button type="primary" link @click="showDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 详情对话框：只显示各题得分，不显示学生答案 -->
    <el-dialog
      v-model="detailVisible"
      :title="`${currentStudent?.name} 的得分详情`"
      width="500px"
      @closed="closeDetail"
    >
      <el-table :data="currentStudent?.question_scores || []" border>
        <el-table-column prop="question_order" label="题号" width="80" />
        <el-table-column label="得分" width="150">
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
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const props = defineProps({
  examId: { type: [String, Number], required: true }
})

const loading = ref(false)
const studentList = ref([])
const examInfo = ref(null)
const detailVisible = ref(false)
const currentStudent = ref(null)
const updatingScores = ref(new Set())

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
}

// 获取成绩数据
const fetchScores = async () => {
  loading.value = true
  try {
    const res = await axios.get(`/api/exams/${props.examId}/scores`)
    if (res.data.code === 1) {
      const data = res.data.data
      examInfo.value = data.exam_info
      studentList.value = data.students.map(s => ({
        ...s,
        grading_status: s.total_score !== null ? 'completed' : 'pending',
        graded_at: s.graded_at || null
      }))
    } else {
      ElMessage.error(res.data.msg || '获取成绩失败')
    }
  } catch (error) {
    console.error('获取成绩失败:', error)
    ElMessage.error('获取成绩失败')
  } finally {
    loading.value = false
  }
}

// 显示详情对话框
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

  // 计算更新后的总分
  let newTotal = 0
  for (const q of currentStudent.value.question_scores) {
    if (q.question_id === questionId) {
      newTotal += newScore
    } else {
      newTotal += (q.score || 0)
    }
  }
  // 校验总分不超过考试总分
  if (examInfo.value?.total_score && newTotal > examInfo.value.total_score) {
    ElMessage.error(`总分不能超过考试总分 ${examInfo.value.total_score} 分`)
    return
  }

  updatingScores.value.add(questionId)
  try {
    const res = await axios.put(`/api/exams/${props.examId}/scores/${studentId}/${questionId}`, {
      score: newScore
    })
    if (res.data.code === 1) {
      ElMessage.success('分数已更新')
      await fetchScores()
      const updatedStudent = studentList.value.find(s => s.student_id === studentId)
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

// 导出Excel
const exportExcel = async () => {
  try {
    const response = await axios.get(`/api/exams/${props.examId}/export`, {
      responseType: 'blob'
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `exam_${props.examId}_scores.xlsx`)
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
  fetchScores()
})
</script>

<style scoped>
.header-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>