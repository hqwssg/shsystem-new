<template>
  <div class="app-container carbon-params-page">
    <div class="params-frame-wrap" v-loading="loading">
      <iframe
        class="params-frame"
        :src="paramsFrameUrl"
        frameborder="0"
        title="碳排放核算参数设置"
        @load="handleFrameLoad"
      ></iframe>
    </div>
  </div>
</template>

<script>
import { resolveServiceUrl } from '@/utils/serviceUrl'
import { getToken } from '@/utils/auth'

export default {
  name: 'CarbonParams',
  data() {
    return {
      loading: true,
      modelUrl: import.meta.env.VUE_APP_CARBON_MODEL_URL || '/carbon-model/'
    }
  },
  computed: {
    paramsFrameUrl() {
      const url = new URL(resolveServiceUrl(this.modelUrl, '/carbon-model/'))
      url.searchParams.set('embedded', '1')
      url.searchParams.set('view', 'params')
      return url.toString()
    }
  },
  mounted() {
    window.addEventListener('message', this.handleFrameMessage)
  },
  beforeUnmount() {
    window.removeEventListener('message', this.handleFrameMessage)
  },
  methods: {
    handleFrameMessage(event) {
      const allowedOrigin = new URL(this.paramsFrameUrl).origin
      if (event.origin !== allowedOrigin) return
      if (event.data && event.data.type === 'carbon:navigate-home') {
        this.$router.push('/carbon/index')
        return
      }
      if (event.data && event.data.type === 'carbon:request-auth-token') {
        this.sendAuthToken(event.source, event.origin)
        return
      }
      if (event.data && event.data.type === 'carbon:auth-expired') {
        this.handleEmbeddedAuthExpired()
      }
    },
    handleEmbeddedAuthExpired() {
      this.$store.dispatch('FedLogOut').finally(() => {
        this.$router.replace({ path: '/login', query: { redirect: this.$route.fullPath } })
      })
    },
    sendAuthToken(target, origin) {
      const token = getToken()
      if (!token || !target || typeof target.postMessage !== 'function') return
      const allowedOrigin = new URL(this.paramsFrameUrl).origin
      if (origin !== allowedOrigin) return
      target.postMessage({ type: 'carbon:set-auth-token', token }, origin)
    },
    handleFrameLoad(event) {
      this.loading = false
      this.sendAuthToken(event.target.contentWindow, new URL(this.paramsFrameUrl).origin)
    }
  }
}
</script>

<style scoped lang="scss">
.carbon-params-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 50px);
  min-height: 0;
  padding: 0;
  background: #f5f7fa;
  box-sizing: border-box;
}

.params-frame-wrap {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: #fff;
}

.params-frame {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 100%;
}

@media (max-width: 780px) {
  .carbon-params-page { height: calc(100dvh - 50px); }
}
</style>
