<template>
  <div class="prediction-page">
    <div class="prediction-frame-wrap" v-loading="loading">
      <iframe
        class="prediction-frame"
        :src="frameUrl"
        title="碳排放趋势预测"
        frameborder="0"
        @load="handleFrameLoad"
      />
    </div>
  </div>
</template>

<script>
import { getToken } from '@/utils/auth'

export default {
  name: 'CarbonPrediction',
  data() {
    return { loading: true }
  },
  computed: {
    frameUrl() {
      const configured = import.meta.env.VUE_APP_PREDICTION_URL || '/prediction/'
      const url = new URL(configured, window.location.origin)
      url.searchParams.set('embedded', '1')
      return url.toString()
    }
  },
  methods: {
    sendAuthToken(target, origin) {
      const token = getToken()
      if (!token || !target || origin !== window.location.origin) return
      target.postMessage({ type: 'carbon:set-auth-token', token }, origin)
    },
    handleFrameMessage(event) {
      if (event.origin !== window.location.origin || !event.data) return
      if (event.data.type === 'carbon:request-auth-token') {
        this.sendAuthToken(event.source, event.origin)
      } else if (event.data.type === 'carbon:navigate-home') {
        this.$router.push('/carbon/index')
      } else if (event.data.type === 'carbon:auth-expired') {
        this.$store.dispatch('FedLogOut').finally(() => {
          this.$router.replace({ path: '/login', query: { redirect: this.$route.fullPath } })
        })
      }
    },
    handleFrameLoad(event) {
      this.loading = false
      this.sendAuthToken(event.target.contentWindow, window.location.origin)
    }
  },
  mounted() { window.addEventListener('message', this.handleFrameMessage) },
  beforeUnmount() { window.removeEventListener('message', this.handleFrameMessage) }
}
</script>

<style scoped>
.prediction-page { height: calc(100vh - 50px); min-height: 0; padding: 0; background: #f5f7fa; }
.prediction-frame-wrap, .prediction-frame { width: 100%; height: 100%; min-height: 0; }
.prediction-frame { display: block; }
</style>
