<template>
  <div class="app-container carbon-model-page">
    <div class="model-frame-wrap" v-loading="loading">
      <iframe
        class="model-frame"
        :src="modelFrameUrl"
        frameborder="0"
        @load="handleFrameLoad"
      ></iframe>
    </div>
  </div>
</template>

<script>
import { resolveServiceUrl } from '@/utils/serviceUrl'
import { getToken } from '@/utils/auth'

export default {
  name: 'CarbonModel',
  data() {
    return {
      loading: true,
      modelUrl: import.meta.env.VUE_APP_CARBON_MODEL_URL || '/carbon-model/'
    }
  },
  computed: {
    resolvedModelUrl() {
      const url = new URL(resolveServiceUrl(this.modelUrl, '/carbon-model/'))
      if (!url.pathname.endsWith('/')) url.pathname += '/'
      return url.toString()
    },
    modelFrameUrl() {
      const url = new URL(this.resolvedModelUrl)
      url.searchParams.set('embedded', '1')
      url.searchParams.set('view', 'model')
      return url.toString()
    }
  },
  methods: {
    handleFrameMessage(event) {
      const allowedOrigin = new URL(this.modelFrameUrl).origin
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
      const allowedOrigin = new URL(this.modelFrameUrl).origin
      if (origin !== allowedOrigin) return
      target.postMessage({ type: 'carbon:set-auth-token', token }, origin)
    },
    handleFrameLoad(event) {
      this.loading = false
      this.sendAuthToken(event.target.contentWindow, new URL(this.modelFrameUrl).origin)
    }
  },
  mounted() {
    window.addEventListener('message', this.handleFrameMessage)
  },
  beforeUnmount() {
    window.removeEventListener('message', this.handleFrameMessage)
  }
}
</script>

<style scoped lang="scss">
.carbon-model-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 50px);
  min-height: 0;
  padding: 0;
  background: #f5f7fa;
  box-sizing: border-box;
}

.model-frame-wrap {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: #fff;
}

.model-frame {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 100%;
}

@media (max-width: 780px) {
  .carbon-model-page { height: calc(100dvh - 50px); }
}
</style>
