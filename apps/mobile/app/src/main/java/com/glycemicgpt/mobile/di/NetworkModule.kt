package com.glycemicgpt.mobile.di

import com.glycemicgpt.mobile.data.remote.AuthInterceptor
import com.glycemicgpt.mobile.data.remote.BaseUrlInterceptor
import com.glycemicgpt.mobile.data.remote.GlycemicGptApi
import com.glycemicgpt.mobile.data.remote.TokenRefreshInterceptor
import com.glycemicgpt.mobile.data.remote.InstantAdapter
import com.squareup.moshi.Moshi
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.ConnectionPool
import okhttp3.Dispatcher
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import com.glycemicgpt.mobile.BuildConfig
import java.util.concurrent.TimeUnit
import javax.inject.Named
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun provideMoshi(): Moshi =
        Moshi.Builder()
            .add(InstantAdapter())
            .build()

    @Provides
    @Singleton
    fun provideOkHttpClient(
        authInterceptor: AuthInterceptor,
        baseUrlInterceptor: BaseUrlInterceptor,
        tokenRefreshInterceptor: TokenRefreshInterceptor,
    ): OkHttpClient {
        val logging = HttpLoggingInterceptor().apply {
            level = if (BuildConfig.DEBUG) {
                HttpLoggingInterceptor.Level.BODY
            } else {
                HttpLoggingInterceptor.Level.NONE
            }
        }
        return OkHttpClient.Builder()
            .addInterceptor(baseUrlInterceptor)
            .addInterceptor(authInterceptor)
            .addInterceptor(tokenRefreshInterceptor)
            .addInterceptor(logging)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            .build()
    }

    @Provides
    @Singleton
    fun provideRetrofit(client: OkHttpClient, moshi: Moshi): Retrofit =
        Retrofit.Builder()
            // Placeholder base URL; BaseUrlInterceptor rewrites it at runtime
            .baseUrl("http://localhost/")
            .client(client)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()

    @Provides
    @Singleton
    fun provideGlycemicGptApi(retrofit: Retrofit): GlycemicGptApi =
        retrofit.create(GlycemicGptApi::class.java)

    /** API instance with a 90-second read timeout for LLM inference calls.
     *  Uses an isolated dispatcher and connection pool to avoid starving other requests. */
    @Provides
    @Singleton
    @Named("chat")
    fun provideChatApi(client: OkHttpClient, moshi: Moshi): GlycemicGptApi {
        val chatClient = client.newBuilder()
            .apply { interceptors().removeAll { it is HttpLoggingInterceptor } }
            .readTimeout(90, TimeUnit.SECONDS)
            .dispatcher(Dispatcher())
            .connectionPool(ConnectionPool(2, 90, TimeUnit.SECONDS))
            .build()
        return Retrofit.Builder()
            .baseUrl("http://localhost/")
            .client(chatClient)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(GlycemicGptApi::class.java)
    }
}
