<!--
  Design read: data-news feature page for general readers, reference-led editorial layout
  (FT Visual and Data Journalism / Reuters Graphics / 澎湃美数课), not a SaaS dashboard.
  Dials: DESIGN_VARIANCE 6 / MOTION_INTENSITY 2 / VISUAL_DENSITY 5.
-->
<script setup>
import { computed, onMounted, ref } from 'vue'

const games = ref([])
const latestMap = ref({})
const current = ref('')
const recs = ref(null)
const stats = ref(null)
const recent = ref([])
const loading = ref(false)
const error = ref('')
const theme = ref('auto')

const currentGame = computed(() => games.value.find(g => g.key === current.value) || null)
const providerGroups = computed(() => [
  { key: 'cwl', name: '福利彩票', games: games.value.filter(g => g.provider === 'cwl') },
  { key: 'sporttery', name: '体育彩票', games: games.value.filter(g => g.provider === 'sporttery') },
])
const latest = computed(() => latestMap.value[current.value] || null)

const maxSum = computed(() => Math.max(...(stats.value?.sum_distribution || []).map(x => x.count), 1))
const oddBars = computed(() => (stats.value?.odd_distribution || []).filter(x => x.count > 0))
const maxOdd = computed(() => Math.max(...oddBars.value.map(x => x.count), 1))

const topFreq = computed(() => {
  const list = [...(stats.value?.frequency || [])]
  list.sort((a, b) => b.count - a.count || a.number - b.number)
  return list.slice(0, 12)
})
const maxTopFreq = computed(() => Math.max(...topFreq.value.map(x => x.count), 1))

const latestSum = computed(() => latest.value ? latest.value.numbers.reduce((a, b) => a + b, 0) : '-')
const latestSpan = computed(() => {
  if (!latest.value?.numbers?.length) return '-'
  return Math.max(...latest.value.numbers) - Math.min(...latest.value.numbers)
})
const latestOdd = computed(() => latest.value ? latest.value.numbers.filter(n => n % 2 === 1).length : '-')

const previous = computed(() => recent.value[1] || null)
const overlapText = computed(() => {
  if (!latest.value || !previous.value) return ''
  if (currentGame.value?.kind === 'digit') return ''
  const prev = new Set(previous.value.numbers)
  const n = latest.value.numbers.filter(x => prev.has(x)).length
  return `与上期重号 ${n} 个。`
})

const topThree = computed(() => {
  const list = [...(stats.value?.frequency || [])]
  list.sort((a, b) => b.count - a.count || a.number - b.number)
  return list.slice(0, 3)
})
const topThreeText = computed(() => topThree.value.map(x => `${pad(x.number)} 号 ${x.count} 次`).join('、'))
const topTied = computed(() => {
  const top = topThree.value[0]
  if (!top) return []
  return topThree.value.filter(x => x.count === top.count).map(x => pad(x.number))
})

const storyHeadline = computed(() => {
  if (!latest.value) return '彩票数据观察'
  const top = topThree.value[0]
  if (!top) return `${latest.value.name}第 ${latest.value.issue} 期开奖`
  const label = topTied.value.length > 1
    ? `${topTied.value.join('、')} 号并列 ${top.count} 次`
    : `${topTied.value[0]} 号出现 ${top.count} 次`
  return `${latest.value.name}第 ${latest.value.issue} 期：和值 ${latestSum.value}，${label}`
})

const storyDeck = computed(() => {
  if (!latest.value || !stats.value) return '官方开奖记录与历史统计。'
  const even = latest.value.numbers.length - latestOdd.value
  return `本期开奖号码 ${latest.value.display}。近 ${stats.value.sample} 期平均和值 ${stats.value.avg_sum}，当前和值 ${latestSum.value}；奇数 ${latestOdd.value} 个，偶数 ${even} 个。`
})

const observation = computed(() => {
  if (!latest.value || !stats.value) return ''
  const relation = latestSum.value >= stats.value.avg_sum ? '高于' : '低于'
  return `和值 ${latestSum.value}，${relation}近 ${stats.value.sample} 期均值 ${stats.value.avg_sum}；近 ${stats.value.sample} 期中，${topThreeText.value} 出现次数最多。${overlapText.value}`
})

const todayLabel = computed(() => {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}.${m}.${day}`
})

function pad(n, w = 2) {
  return String(n).padStart(w, '0')
}

function money(v) {
  if (v === null || v === undefined) return '-'
  return Number(v).toLocaleString('zh-CN')
}

function pct(v, max) {
  return `${Math.max(3, Math.round((v / max) * 100))}%`
}

function drawSum(d) {
  return d.numbers.reduce((a, b) => a + b, 0)
}

function drawSpan(d) {
  if (!d.numbers?.length) return '-'
  return Math.max(...d.numbers) - Math.min(...d.numbers)
}

function drawOdd(d) {
  return d.numbers.filter(n => n % 2 === 1).length
}

async function getJSON(url) {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

async function loadGame() {
  if (!current.value) return
  loading.value = true
  error.value = ''
  try {
    const [r, s, d] = await Promise.all([
      getJSON(`/api/recommendations?game=${current.value}`),
      getJSON(`/api/stats/${current.value}`),
      getJSON(`/api/draws?game=${current.value}&limit=6`),
    ])
    recs.value = r
    stats.value = s
    recent.value = d.items || []
  } catch (e) {
    error.value = e.message || String(e)
    recs.value = null
    stats.value = null
    recent.value = []
  } finally {
    loading.value = false
  }
}

async function selectGame(key) {
  if (current.value === key) return
  current.value = key
  await loadGame()
}

function applyTheme(value) {
  const root = document.documentElement
  if (value === 'auto') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', value)
}

function setTheme(value) {
  theme.value = value
  try { localStorage.setItem('lottery-theme', value) } catch (e) {}
  applyTheme(value)
}

onMounted(async () => {
  try {
    const saved = localStorage.getItem('lottery-theme')
    if (saved === 'light' || saved === 'dark' || saved === 'auto') theme.value = saved
  } catch (e) {}
  applyTheme(theme.value)

  try {
    const [g, l] = await Promise.all([getJSON('/api/games'), getJSON('/api/latest')])
    games.value = g
    latestMap.value = Object.fromEntries(l.map(x => [x.game, x]))
    current.value = g[0]?.key || ''
    await loadGame()
  } catch (e) {
    error.value = e.message || String(e)
  }
})
</script>

<template>
  <div class="page">
    <header class="masthead">
      <div class="brand-bar">
        <div class="brand">
          <span class="brand-name">彩票数据观察</span>
          <span class="brand-en">LOTTERY DATA REVIEW</span>
        </div>
        <div class="masthead-tools">
          <div class="theme-switch" role="group" aria-label="主题切换">
            <button
              :class="{ active: theme === 'light' }"
              :aria-pressed="theme === 'light'"
              @click="setTheme('light')"
            >浅色</button>
            <button
              :class="{ active: theme === 'dark' }"
              :aria-pressed="theme === 'dark'"
              @click="setTheme('dark')"
            >深色</button>
            <button
              :class="{ active: theme === 'auto' }"
              :aria-pressed="theme === 'auto'"
              @click="setTheme('auto')"
            >自动</button>
          </div>
          <time class="date">{{ todayLabel }}</time>
        </div>
      </div>

      <section class="lottery-index" aria-label="彩票类型与玩法">
        <div v-for="group in providerGroups" :key="group.key" class="index-group">
          <div class="index-label">{{ group.name }}</div>
          <div class="index-links">
            <button
              v-for="g in group.games"
              :key="g.key"
              class="index-link"
              :class="{ active: current === g.key }"
              @click="selectGame(g.key)"
            >
              {{ g.name }}
            </button>
          </div>
        </div>
      </section>

      <div class="story-head">
        <h1>{{ storyHeadline }}</h1>
        <p class="story-deck">{{ storyDeck }}</p>
        <p class="byline">数据来源：官方公开开奖接口 / 更新于 {{ todayLabel }}</p>
      </div>
    </header>

    <main class="content">
      <div v-if="error" class="error">读取失败：{{ error }}</div>

      <section v-if="latest" class="lead-grid">
        <div class="lead-main">
          <div class="draw-kicker">
            <span>开奖号码</span>
            <span>第 {{ latest.issue }} 期 / {{ latest.draw_date }}</span>
          </div>

          <div class="draw-plate" :class="{ dense: latest.numbers.length > 10 }">
            <span
              v-for="(n, i) in latest.numbers"
              :key="'n' + i"
              class="ball"
            >{{ pad(n, currentGame?.kind === 'digit' ? 1 : 2) }}</span>
            <span v-if="latest.extra.length" class="ball-split">+</span>
            <span
              v-for="(n, i) in latest.extra"
              :key="'e' + i"
              class="ball ball-extra"
            >{{ pad(n) }}</span>
          </div>

          <div class="lead-stats">
            <div><span>和值</span><strong>{{ latestSum }}</strong></div>
            <div><span>跨度</span><strong>{{ latestSpan }}</strong></div>
            <div><span>奇偶</span><strong>{{ latestOdd }}:{{ latest.numbers.length - latestOdd }}</strong></div>
            <div><span>销售额</span><strong>{{ money(latest.sales) }}</strong></div>
            <div><span>奖池</span><strong>{{ money(latest.pool) }}</strong></div>
          </div>

          <section v-if="observation" class="observation">
            <p class="observation-label">本期观察</p>
            <p class="observation-text">{{ observation }}</p>
          </section>
        </div>

        <aside class="lead-side">
          <div class="section-head">
            <h2>下期参考</h2>
            <div v-if="recs?.target_issue" class="side-meta">
              <span>第 {{ recs.target_issue }} 期</span>
              <span v-if="recs.target_date">开奖日期 {{ recs.target_date }}</span>
            </div>
          </div>

          <div v-if="loading" class="empty">读取数据中。</div>
          <div v-else-if="!recs?.items?.length" class="empty">暂无推荐，等待每日任务更新。</div>
          <ol v-else class="rec-list compact">
            <li v-for="item in recs.items" :key="item.rank">
              <span class="rec-index">{{ pad(item.rank) }}</span>
              <div class="rec-body">
                <div class="rec-numbers">{{ item.display }}</div>
                <p class="rec-reason" :title="item.rationale">{{ item.rationale }}</p>
              </div>
            </li>
          </ol>
        </aside>
      </section>

      <div class="rule"></div>

      <section class="mid-grid">
        <div class="freq-block">
          <div class="section-head">
            <h2>热号 Top 12</h2>
            <span class="meta">近 {{ stats?.sample || 0 }} 期出现次数</span>
          </div>
          <div class="freq-bars">
            <div v-for="f in topFreq" :key="f.number" class="freq-bar-row">
              <span class="freq-bar-num">{{ pad(f.number) }}</span>
              <div class="freq-bar-track">
                <div class="freq-bar" :style="{ width: pct(f.count, maxTopFreq) }"></div>
              </div>
              <span class="freq-bar-count">{{ f.count }}</span>
            </div>
          </div>
        </div>

        <aside class="structure-block">
          <div class="section-head">
            <h2>结构</h2>
            <span class="meta">近 {{ stats?.sample || 0 }} 期</span>
          </div>

          <div v-if="stats" class="stat-list">
            <div class="stat-row"><span>平均和值</span><strong>{{ stats.avg_sum }}</strong></div>
            <div class="stat-row"><span>和值标准差</span><strong>{{ stats.std_sum }}</strong></div>
            <div class="stat-row"><span>平均跨度</span><strong>{{ stats.avg_span }}</strong></div>
          </div>

          <div class="read-note">
            <h3>阅读说明</h3>
            <p>频率和遗漏只描述历史。每期开奖独立，历史数据不改变下一期的理论概率。</p>
            <p>推荐组合按结构评分排序，分数不是中奖概率。</p>
          </div>
        </aside>
      </section>

      <div class="rule"></div>

      <section v-if="stats" class="dist-grid">
        <div class="dist-block">
          <div class="section-head">
            <h2>和值分布</h2>
            <span class="meta">近 {{ stats?.sample || 0 }} 期</span>
          </div>
          <div class="bars">
            <div v-for="b in stats.sum_distribution" :key="b.label" class="bar-item">
              <span class="bar-value">{{ b.count }}</span>
              <div class="bar-track">
                <div class="bar" :style="{ height: pct(b.count, maxSum) }"></div>
              </div>
              <span class="bar-label">{{ b.label }}</span>
            </div>
          </div>
        </div>

        <div class="dist-block">
          <div class="section-head">
            <h2>奇数个数</h2>
            <span class="meta">近 {{ stats?.sample || 0 }} 期</span>
          </div>
          <div class="bars">
            <div v-for="b in oddBars" :key="b.odd" class="bar-item">
              <span class="bar-value">{{ b.count }}</span>
              <div class="bar-track">
                <div class="bar" :style="{ height: pct(b.count, maxOdd) }"></div>
              </div>
              <span class="bar-label">{{ b.odd }}</span>
            </div>
          </div>
        </div>
      </section>

      <div class="rule"></div>

      <section class="ledger">
        <div class="section-head">
          <h2>近期开奖</h2>
          <span class="meta">最近 6 期</span>
        </div>
        <table>
          <thead>
            <tr><th>期号</th><th>开奖号码</th><th>和值</th><th>跨度</th><th>奇偶</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in recent" :key="d.issue">
              <td class="mono">{{ d.issue }}</td>
              <td class="mono ledger-nums" :title="d.display">{{ d.display }}</td>
              <td class="mono">{{ drawSum(d) }}</td>
              <td class="mono">{{ drawSpan(d) }}</td>
              <td class="mono">{{ drawOdd(d) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </main>

    <footer class="foot">
      <div class="foot-mark">彩票数据观察</div>
      <p>数据来源：中国福利彩票网、中国体彩网官方公开接口。</p>
      <p>彩票每期独立开奖，历史统计不能预测下一期。未成年人不得购彩。</p>
    </footer>
  </div>
</template>
