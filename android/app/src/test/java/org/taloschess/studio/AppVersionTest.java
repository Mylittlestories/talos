package org.taloschess.studio;

import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** Version codes sent to Android must be positive and monotonic release values. */
public class AppVersionTest {
    @Test
    public void configuredVersionCodeIsPositive() {
        assertTrue(BuildConfig.VERSION_CODE > 0);
    }
}
