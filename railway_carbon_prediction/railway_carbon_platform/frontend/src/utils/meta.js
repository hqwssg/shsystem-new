import { onMounted, ref } from 'vue'
import { getMeta } from '../api'
import { ORG_LABEL, VAR_LABEL } from './dict'

export function useMeta() {
  const orgs = ref([])
  const vars = ref([])
  const loading = ref(false)

  const load = async () => {
    loading.value = true
    try {
      const data = await getMeta()
      orgs.value = data.orgs || []
      vars.value = data.vars || []
    } finally {
      loading.value = false
    }
  }

  const orgName = (orgId) => {
    const hit = orgs.value.find((x) => x.orgId === orgId)
    return hit?.orgName || ORG_LABEL[orgId] || orgId || '—'
  }

  const varName = (varId) => {
    const hit = vars.value.find((x) => x.varId === varId)
    return hit?.varName || VAR_LABEL[varId] || varId || '—'
  }

  const varUnit = (varId) => vars.value.find((x) => x.varId === varId)?.unit || ''

  // 业务规则：货运周转量、牵引电力仅机辆分公司使用。
  const varsForOrg = (orgId) => {
    if (!orgId || orgId === 'JLG') return vars.value
    return vars.value.filter((x) => !['TURNOVER', 'ELEC_TRAC'].includes(x.varId))
  }

  onMounted(load)

  return { orgs, vars, loading, load, orgName, varName, varUnit, varsForOrg }
}
