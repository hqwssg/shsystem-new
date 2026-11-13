<template>
  <div class="go-project">
    <n-layout has-sider position="absolute">
      <n-space vertical>
        <project-layout-sider></project-layout-sider>
      </n-space>
      <n-layout>
        <layout-header-pro>
          <template #ri-left>
            <n-button size="small" @click="returnToMain">
              <template #icon>
                <n-icon><HomeIcon /></n-icon>
              </template>
              返回主页面
            </n-button>
          </template>
        </layout-header-pro>
        <n-layout
          id="go-project-content-top"
          class="content-top"
          position="absolute"
          :native-scrollbar="false"
        >
          <n-layout-content>
            <layout-transition-main>
              <router-view></router-view>
            </layout-transition-main>
          </n-layout-content>
        </n-layout>
      </n-layout>
    </n-layout>
  </div>
</template>

<script setup lang="ts">
import { ProjectLayoutSider } from './layout/components/ProjectLayoutSider'
import { LayoutHeaderPro } from '@/layout/components/LayoutHeaderPro'
import { LayoutTransitionMain } from '@/layout/components/LayoutTransitionMain/index'
import { icon } from '@/plugins'
import { mainApplicationUrl } from '@/utils/mainApplication'

const { HomeIcon } = icon.ionicons5

const returnToMain = () => window.location.assign(mainApplicationUrl())
</script>

<style lang="scss" scoped>
@include go(project) {
  .content-top {
    top: $--header-height;
    margin-top: 1px;
  }
}
</style>
