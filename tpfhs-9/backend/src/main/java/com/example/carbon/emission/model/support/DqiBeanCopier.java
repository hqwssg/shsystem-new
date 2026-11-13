package com.example.carbon.emission.model.support;

import org.springframework.beans.BeanWrapper;
import org.springframework.beans.BeanWrapperImpl;

/** Copies only the EF DQI contract fields between entities and API DTOs. */
public final class DqiBeanCopier {
    private static final String[] FACTOR_PROPERTIES = {
            "efSourceAuthority", "efCompletenessScope", "efDataRegion", "efDataYear",
            "efTechApplicability", "efConversionChain", "dqiE1Score", "dqiE2Score",
            "dqiE3Score", "dqiE4Score", "dqiE5Score", "dqiE6Score"
    };

    private DqiBeanCopier() {
    }

    public static void copyFactorFields(Object source, Object target) {
        BeanWrapper sourceWrapper = new BeanWrapperImpl(source);
        BeanWrapper targetWrapper = new BeanWrapperImpl(target);
        for (String property : FACTOR_PROPERTIES) {
            targetWrapper.setPropertyValue(property, sourceWrapper.getPropertyValue(property));
        }
    }
}
