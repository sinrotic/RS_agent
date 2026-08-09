package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.domain.AgentProfileFailurePolicy;
import com.sinrotic.rs.agent.domain.AgentPublicOutputBlock;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

@ConfigurationProperties(prefix = "rs.agent.templates")
public class AgentTemplateProperties {

    private String defaultProfile = "shopping-assistant";

    private List<Profile> profiles = new ArrayList<>(List.of(Profile.shoppingAssistant()));

    public String getDefaultProfile() {
        return defaultProfile;
    }

    public void setDefaultProfile(String defaultProfile) {
        this.defaultProfile = defaultProfile;
    }

    public List<Profile> getProfiles() {
        return profiles;
    }

    public void setProfiles(List<Profile> profiles) {
        this.profiles = profiles;
    }

    public static Profile builtInShoppingAssistant() {
        return Profile.shoppingAssistant();
    }

    public static class Profile {

        private String id;

        private String modelRef;

        private String systemPromptRef;

        private List<String> allowedCapabilities = new ArrayList<>();

        private List<AgentPublicOutputBlock> allowedOutputBlocks = new ArrayList<>();

        private int maxLoops;

        private AgentProfileFailurePolicy failurePolicy;

        static Profile shoppingAssistant() {
            Profile profile = new Profile();
            profile.id = "shopping-assistant";
            profile.modelRef = "default";
            profile.systemPromptRef = "default";
            profile.allowedCapabilities = new ArrayList<>(List.of(
                    "recommend",
                    "rag-explain",
                    "session-memory"
            ));
            profile.allowedOutputBlocks = new ArrayList<>(List.of(
                    AgentPublicOutputBlock.TEXT,
                    AgentPublicOutputBlock.PRODUCT_CARDS,
                    AgentPublicOutputBlock.COMPARISON_TABLE,
                    AgentPublicOutputBlock.FOLLOWUP_QUESTION
            ));
            profile.maxLoops = 8;
            profile.failurePolicy = AgentProfileFailurePolicy.FAIL_TURN;
            return profile;
        }

        public String getId() {
            return id;
        }

        public void setId(String id) {
            this.id = id;
        }

        public String getModelRef() {
            return modelRef;
        }

        public void setModelRef(String modelRef) {
            this.modelRef = modelRef;
        }

        public String getSystemPromptRef() {
            return systemPromptRef;
        }

        public void setSystemPromptRef(String systemPromptRef) {
            this.systemPromptRef = systemPromptRef;
        }

        public List<String> getAllowedCapabilities() {
            return allowedCapabilities;
        }

        public void setAllowedCapabilities(List<String> allowedCapabilities) {
            this.allowedCapabilities = allowedCapabilities;
        }

        public List<AgentPublicOutputBlock> getAllowedOutputBlocks() {
            return allowedOutputBlocks;
        }

        public void setAllowedOutputBlocks(List<AgentPublicOutputBlock> allowedOutputBlocks) {
            this.allowedOutputBlocks = allowedOutputBlocks;
        }

        public int getMaxLoops() {
            return maxLoops;
        }

        public void setMaxLoops(int maxLoops) {
            this.maxLoops = maxLoops;
        }

        public AgentProfileFailurePolicy getFailurePolicy() {
            return failurePolicy;
        }

        public void setFailurePolicy(AgentProfileFailurePolicy failurePolicy) {
            this.failurePolicy = failurePolicy;
        }
    }
}
