#ifndef SMNCSFTMT_H_
#define SMNCSFTMT_H_
//#include <stdint.h>
//device connected types
#define FTMT_DEV_CONNECTED_USB			(1)
#define FTMT_DEV_CONNECTED_SFP			(2)

//device types
#define FTMT_DEV_TYPE_FT1010			(0x1010)
#define FTMT_DEV_TYPE_FT1040			(0x1040)
#define FTMT_DEV_TYPE_FT1080			(0x1080)
#define FTMT_DEV_TYPE_MT6420			(0x6420)
#define FTMT_DEV_TYPE_MT04				(0x0004)
#define FTMT_DEV_TYPE_MT08				(0x0008)
#define FTMT_DEV_TYPE_MT16				(0x0016)

//Start signal frequency division(MT4C16 is not supported)
#define FTMT_START_FREQ_DIV_1			(1)
#define FTMT_START_FREQ_DIV_2			(2)
#define FTMT_START_FREQ_DIV_4			(4)
#define FTMT_START_FREQ_DIV_8			(8)

//resolution
#define FTMT_WIN_RES_PS_1				(0)
#define FTMT_WIN_RES_PS_2				(1)
#define FTMT_WIN_RES_PS_4				(2)
#define FTMT_WIN_RES_PS_8				(3)
#define FTMT_WIN_RES_PS_16				(4)
#define FTMT_WIN_RES_PS_32				(5)
#define FTMT_WIN_RES_PS_64				(6)
#define FTMT_WIN_RES_PS_128				(7)
#define FTMT_WIN_RES_PS_256				(8)
#define FTMT_WIN_RES_PS_512				(9)
#define FTMT_WIN_RES_PS_1024			(10)
#define FTMT_WIN_RES_PS_2048			(11)
#define FTMT_WIN_RES_PS_4096			(12)
#define FTMT_WIN_RES_PS_8192			(13)
#define FTMT_WIN_RES_PS_16384			(14)
#define FTMT_WIN_RES_PS_32768			(15)
#define FTMT_WIN_RES_PS_65536			(16)
#define FTMT_WIN_RES_PS_131072			(17)
#define FTMT_WIN_RES_PS_262144			(18)
#define FTMT_WIN_RES_PS_524288			(19)
#define FTMT_WIN_RES_PS_1048576			(20)
#define FTMT_WIN_RES_PS_2097152			(21)
#define FTMT_WIN_RES_PS_4194304			(22)
#define FTMT_WIN_RES_PS_8388608			(23)
#define FTMT_WIN_RES_PS_16777216		(24)
#define FTMT_WIN_RES_PS_33554432		(25)

//Run mode
#define FTMT_TASK_RUN_MODE_T1			(0x01)
#define FTMT_TASK_RUN_MODE_T2			(0x02)
#define FTMT_TASK_RUN_MODE_T3			(0x03)
#define FTMT_TASK_RUN_MODE_CO			(0x04)
#define FTMT_TASK_RUN_MODE_ITTR_T		(0x06)
#define FTMT_TASK_RUN_MODE_ITTR_M		(0x07)
#define FTMT_TASK_RUN_MODE_G2		    (0x08)
#define FTMT_TASK_RUN_MODE_MULTI_CO		(0x09)
#define FTMT_TASK_RUN_MODE_IDLE			(0x10)
#define FTMT_TASK_RUN_MODE_ERR			(0x20)

//Board number
#define FTMT_BOARD_A				(0)
#define FTMT_BOARD_B				(1)
#define FTMT_BOARD_C				(2)
#define FTMT_BOARD_D				(3)
#define FTMT_BOARD_E				(4)
#define FTMT_BOARD_F				(5)
#define FTMT_BOARD_G				(6)
#define FTMT_BOARD_H				(7)

//Channel number
#define FTMT_CHANNEL_0				(0)
#define FTMT_CHANNEL_1				(1)
#define FTMT_CHANNEL_2				(2)
#define FTMT_CHANNEL_3				(3)
#define FTMT_CHANNEL_4				(4)
#define FTMT_CHANNEL_5				(5)
#define FTMT_CHANNEL_6				(6)
#define FTMT_CHANNEL_7				(7)
#define FTMT_CHANNEL_8				(8)
#define FTMT_CHANNEL_9				(9)
#define FTMT_CHANNEL_10				(10)
#define FTMT_CHANNEL_11				(11)
#define FTMT_CHANNEL_12				(12)
#define FTMT_CHANNEL_13				(13)
#define FTMT_CHANNEL_14				(14)
#define FTMT_CHANNEL_15				(15)

//Save type
#define FTMT_FILE_SAVE_MODE_NONE		(0)
#define FTMT_FILE_SAVE_MODE_BIN			(1)
#define FTMT_FILE_SAVE_MODE_TEXT		(2)

//Save mode
#define FTMT_FILE_SERIES_MODE_EACH		(0)
#define FTMT_FILE_SERIES_MODE_LAST		(1)

//Save cut
#define FTMT_FILE_CUT_MODE_NONE			(0)
#define FTMT_FILE_CUT_MODE_SIZE			(1)
#define FTMT_FILE_CUT_MODE_TIME			(2)

//TTTR end mode
#define FTMT_TTTR_END_MODE_TIME			(0)
#define FTMT_TTTR_END_MODE_EVENT		(1)

//ITTR end mode
#define FTMT_ITTR_END_MODE_TIME			(0)
#define FTMT_ITTR_END_MODE_EVENT		(1)

//Input impedence(only FT10X0)
#define FT10X0_INPUT_IMPEDENCE_HIGH		(0)
#define FT10X0_INPUT_IMPEDENCE_50		(1)

//only MT4C16
#define MT4C16_INPUT_IMPEDENCE_HIGH		(0)
#define MT4C16_INPUT_IMPEDENCE_50		(1)

#define FT10X0_INPUT_EDGE_RISE			(0)
#define FT10X0_INPUT_EDGE_FALL			(1)

#define MT4C16_INPUT_EDGE_RISE			(0)
#define MT4C16_INPUT_EDGE_FALL			(1)

#define FTMT_FILENAME_AUTO			(0)
#define FTMT_FILENAME_MANUAL			(1)

#define CH_MASK_0				((short)(0x01))
#define CH_MASK_1				((short)(0x01<<FTMT_CHANNEL_1))
#define CH_MASK_2				((short)(0x01<<FTMT_CHANNEL_2))
#define CH_MASK_3				((short)(0x01<<FTMT_CHANNEL_3))
#define CH_MASK_4				((short)(0x01<<FTMT_CHANNEL_4))
#define CH_MASK_5				((short)(0x01<<FTMT_CHANNEL_5))
#define CH_MASK_6				((short)(0x01<<FTMT_CHANNEL_6))
#define CH_MASK_7				((short)(0x01<<FTMT_CHANNEL_7))
#define CH_MASK_8				((short)(0x01<<FTMT_CHANNEL_8))
#define CH_MASK_9				((short)(0x01<<FTMT_CHANNEL_9))
#define CH_MASK_10				((short)(0x01<<FTMT_CHANNEL_10))
#define CH_MASK_11				((short)(0x01<<FTMT_CHANNEL_11))
#define CH_MASK_12				((short)(0x01<<FTMT_CHANNEL_12))
#define CH_MASK_13				((short)(0x01<<FTMT_CHANNEL_13))
#define CH_MASK_14				((short)(0x01<<FTMT_CHANNEL_14))
#define CH_MASK_15				((short)(0x01<<FTMT_CHANNEL_15))
#define CH_MASK_NONE			((short)(0x0000))
#define CH_MASK_ALL				((short)(0xFFFF))

//device number
#define DEV_ID_0				(0)
#define DEV_ID_1				(1)
#define DEV_ID_2				(2)
#define DEV_ID_3				(3)
#define DEV_ID_4				(4)
#define DEV_ID_5				(5)
#define DEV_ID_6				(6)
#define DEV_ID_7				(7)
#define DEV_MAX_NUMBER				(8)

//error code
#define FTMT_ERROR_NONE				(0)					//no error
#define FTMT_ERROR_CONNECT			(0x1001)			//connection error
#define FTMT_ERROR_SYSTEM_BUSY			(0x1002)			//system is running on another task
#define FTMT_ERROR_PARAM			(0x1003)			//parameter specified is incorrect
#define FTMT_ERROR_MEMORY_ACCESS		(0x1004)			//memory specified could not be accessed	
#define FTMT_ERROR_MEMORY_LOW			(0x1005)			//operating system memory is low
#define FTMT_ERROR_FILE_ACCESS			(0x1006)			//file/directory specified could not be accessed
#define FTMT_ERROR_CHANNEL_ENABLE		(0x1007)			//no channel is enabled for operation
#define FTMT_ERROR_TTTR_ENABLE			(0x1008)			//no tttr is enabled for operation
#define FTMT_ERROR_BOARD_ENABLE			(0x1009)			//no board is enabled for operation
#define FTMT_ERROR_NO_MODE			(0x1010)			//the mode is not defined
#define FTMT_ERROR_MODE_MATCH			(0x1011)			//the mode specified does not match with system
#define FTMT_ERROR_START_LIMIT			(0x1012)			//strategy definition failed due to resource limit
#define FTMT_ERROR_DLL_INIT			(0x1013)			//DLL init failed
#define FTMT_ERROR_FPGA_READY			(0x1014)
#define FTMT_ERROR_FATAL			(0x1015)			//fatal error, please reload the dll

#define FTMT_ERROR_NULLPTR			(0x1016)			//The passed in pointer is null
#define FTMT_ERROR_DEV_NUMBER			(0x1017)			//Device number error (Should enter,0~7)
#define FTMT_ERROR_NO_SUPPORT			(0x1018)			//no support
#define FTMT_ERROR_CHANNEL				(0x1019)			//channel number error
#define FTMT_ERROR_BOARD				(0x1020)			//board number error
#define FTMT_ERROR_FILE_NOT_EXIST		(0x1021)			//file does not exist

#define FT1010_CHANNEL_NUM			(1)					//FT1010 channel num
#define FT1040_CHANNEL_NUM			(4)					//FT1040 channel num
#define FT1080_CHANNEL_NUM			(8)					//FT1080 channel num
#define MT04_CHANNEL_NUM			(4)					//MT04 channel num
#define MT08_CHANNEL_NUM			(8)					//MT08 channel num
#define MT16_CHANNEL_NUM			(16)				//MT16 channel num

#define MT6420_BOARD_NUM			(8)					//MT6420 board num
#define MT6420_CHANNEL_NUM_PER_BOARD		(8)					//MT6420 channel num

#define FTMT_T1_DATA_LEN			(65536*16)		
#define FTMT_DMTCH_BAR_LEN			(65536)

#define DMTCH_MODE_ONLINE			(0)					//online
#define DMTCH_MODE_OFFLINE			(1)					//offline

#define FTMT_DATA_TYPE_T2			(0)
#define FTMT_DATA_TYPE_T3			(1)

#define FTMT_G2_ONLINE					(0)
#define FTMT_G2_OFFLINE					(1)

#define FTMT_MULTI_CO_ONLINE			(0)
#define FTMT_MULTI_CO_OFFLINE			(1)


typedef struct tagFtmtRawData
{
	//tagFtmtRawData()
	//{
	//	nType = 0;
	//	lLength = 0;
	//	ptrData = nullptr;
	//}

	int				nType;
	long			lLength;
	unsigned char* ptrData;
}FtmtRawData;

#define MAX_GROUP (8)
#define MAX_CHANNEL_NUM (64)
#define MAX_NAME_SIZE (32)

typedef struct tagSingleGroup
{
	int				nChlNum;
	int				nGroupCount;
	int				nEffectiveType;
	int				nIntegrate;
	unsigned long long			uWinWidth;
	char strGroupName[MAX_NAME_SIZE];	
	int arrChlNo[MAX_CHANNEL_NUM];
	int arrChlFlag[MAX_CHANNEL_NUM];
}SingleGroup;

typedef struct tagSingleCluster
{
	int				nGroupNum;
	int				nGroupCount;
	int				nIntegrate;
	unsigned long long			uWinWidth;
	char strClusterName[MAX_NAME_SIZE];
	int				arrChlNum[MAX_GROUP];
	int				arrGroupCount[MAX_GROUP];
	int				arrEffectiveType[MAX_GROUP];
	int				arrIntegrate[MAX_GROUP];
	unsigned long long			arrWinWidth[MAX_GROUP];
	int arrChlNo[MAX_GROUP][MAX_CHANNEL_NUM];
	int arrChlFlag[MAX_GROUP][MAX_CHANNEL_NUM];
	char strGroupName[MAX_GROUP][MAX_NAME_SIZE];
}SingleCluster;

#ifdef SMNCSFTMT_LIBRARY_BUILD
// Building the library
#ifdef _WINDOWS
	// Use the Windows-specific export attribute
#define TDC_API __declspec(dllexport)
#elif __GNUC__ >= 4
	// Use the GCC-specific export attribute
#define TDC_API __attribute__((visibility("default")))
#else
	// Assume that no export attributes are needed
#define TDC_API
#endif
#else
// Using (including) the library
#ifdef _WINDOWS
	// Use the Windows-specific import attribute
#define TDC_API __declspec(dllimport)
#else
	// Assume that no import attributes are needed
#define TDC_API
#endif
#endif

#ifdef __cplusplus
extern "C"
{
#endif
	//上面的代码是必须要有的

	TDC_API int InitDll();

	TDC_API int InitDev();

	TDC_API int GetConnectionMode(int nDevId, int* nConnectedType);

	TDC_API int UnInitDll();

	TDC_API char* GetDllVersion();

	TDC_API char* GetFPGAVersion(int nDevId, int nBoardNum);

	TDC_API void FreeFPGAString(char* strFPGA);

	TDC_API bool DevConnected(int nDevId);

	TDC_API bool GetBoardConn(int nDevId, int nBoard);

	TDC_API int GetDevType(int nDevId, unsigned int* ptrType);

	TDC_API char* GetSerialNumber(int nDevId);

	TDC_API void FreeSerialNumberStr(char* strSerial);

	TDC_API char* GetPartNumber(int nDevId);

	TDC_API void FreePartNumString(char* strPartNum);

	TDC_API unsigned int GetSyncStatus(int nDevId, int nBoard);

	TDC_API unsigned int GetStopStatus(int nDevId, int nBoard, int nChannel);

	TDC_API int GetSignalStatus(int nDevId, int nBoard, int nChannel, unsigned int* ptrStartCount, unsigned int* ptrStopCount);

	//Set parameters
	TDC_API int SetStartFreqDiv(int nDevId, int nFreqDiv);   //1,2,4,8

	TDC_API int GetStartFreqDiv(int nDevId, int nBoard, unsigned int* nFreqDiv);

	TDC_API int SetTimeWindowRes(int nDevId, unsigned int nWinRes); //0~25

	TDC_API int GetTimeWindowRes(int nDevId, int nBoard, unsigned int* nWinRes);

	TDC_API int SetBlockedWindow(int nDevId, float fBlockWind);

	TDC_API int SetStartThreshold(int nDevId, int nBoard, int nStartThrsh);

	TDC_API int SetStopThreshold(int nDevId, int nBoard, int nChannel, int nStopThrsh);

	TDC_API int GetStartStopThreshold(int nDevId, int nBoard, int nChannel, int* nStartThreshold, int* nStopThreshold);

	TDC_API int SetStartDelay(int nDevId, int nBoard, float fDelay);

	TDC_API int SetStopDelay(int nDevId, int nBoard, int nChannel, float fDelay);

	TDC_API int GetStopDelay(int nDevId, int nBoard, int nChannel, float* fDelay);

	TDC_API int SetGateHLWidth(int nDevId, int nWidth);

	TDC_API int GetGateHLWidth(int nDevId, int* nWidth);

	TDC_API int SetGateDelay(int nDevId, int nDelay);

	TDC_API int GetGateDelay(int nDevId, int* nDelay);

	TDC_API int SetGateControl(int nDevId, int nGateControl);

	TDC_API int GetGateControl(int nDevId, int* nGateControl);

	TDC_API int SetStartImpedence(int nDevId, int nImpedence);

	TDC_API int GetStartImpedence(int nDevId, int nBoard, unsigned int* nImpedence);

	TDC_API int SetStopImpedence(int nDevId, int nBoard, int nChannel, int nImpedence);

	TDC_API int GetStopImpedence(int nDevId, int nBoard, int nChannel, unsigned int* nEdge);

	TDC_API int SetStartEdge(int nDevId, int nEdge);

	TDC_API int GetStartEdge(int nDevId, int nBoard, unsigned int* nEdge);

	TDC_API int SetStopEdge(int nDevId, int nBoard, int nChannel, int nEdge);

	TDC_API int GetStopEdge(int nDevId, int nBoard, int nChannel, unsigned int* nEdge);

	TDC_API int SetT1T3WindowBack(int nDevId, int nBoard, unsigned int uWindowBack);

	TDC_API int GetT1T3WindowBack(int nDevId, int nBoard, unsigned int* uWindowBack);

	TDC_API int SetPulseCycle(int nDevId, int nBoard, int nCycle);

	TDC_API int SetFilePath(int nDevId, int nRunMode, const char* strFilePath);

	TDC_API char* GetFilePath(int nDevId, int nRunMode);

	TDC_API void FreeFilePathStr(char* strFilePath);

	TDC_API int SetFileName(int nDevId, int nRunMode, int nAutoNaming, const char* strFileName);

	TDC_API char* GetFileName(int nDevId);

	TDC_API void FreeFileNameStr(char* strFileName);

	TDC_API int SetFileMode(int nRunMode, int nSaveMode, int nFilterMode);

	TDC_API int SetMaxFileSize(int nRunMode, int nCutMode, unsigned int nFileSize, unsigned int nSplitTime);

	TDC_API int SetStatisticsTime(int nRunMode, float Times);

	//T1
	TDC_API int SetT1Interval(float fIntvl);

	TDC_API int SetBinSize(int nDevId, unsigned int uBinSize);

	TDC_API int SetMaxBarValue(unsigned long long uValue64);

	TDC_API int EnableT1(int nDevId, int nBoard, unsigned short uMask16);

	TDC_API int GetT1Data(int nBoard, int nChannel, unsigned long long* data);

	TDC_API int GetT1Status(unsigned int* uXMax, unsigned int* uXLastNoZeroValue, unsigned long long* uYMax, unsigned long long* uCount, char* strFileName);

	//ITTR
	TDC_API int EnableITTR(int nDevId, int nBoard, unsigned short uMask16);

	TDC_API int SetITTREndMode(int nMode, unsigned long long uEvents64);

	TDC_API int SetITTRInterval(int nDevId, int nBoard, int nIntvl);

	TDC_API int GetIttrDataOverflow(int nDevId, int nBoard, unsigned int* uDataOverflow);
	//TTTR
	TDC_API int EnableTTTR(int nDevId, int nBoard, unsigned short uMask16);

	TDC_API int SetTTTREndMode(int nEndMode, unsigned long long uEvents64);

	TDC_API int GetTttrDataOverflow(int nDevId, int nBoard, unsigned int* uDataOverflow);

	TDC_API int DmtchInitialize(int nDevId, int nBoard);

	TDC_API int DmtchModeSelection(int nDevId, int nMethod);

	TDC_API int DmtchStartOffLine(const char* strFileName);

	TDC_API bool IsDmtchCompleted(unsigned int* uProgress);

	TDC_API int DmtchAddStrategy(int nIndex, int nStr[], int nNum, unsigned long long nWinLen, float times, int nRes, float fFreq, int nDataType);

	TDC_API unsigned long long DmtchGetStratgyCount(int nIndex);

	TDC_API int DmtchGetChlCount(unsigned long long chlCnt[]);

	TDC_API int DmtchStopOffLine();

	TDC_API unsigned long long DmtchGetTotalTime(int nIndex);

	TDC_API int SetG2BinSize(int nDevId, unsigned int uBinSize);

	TDC_API int EnableG2(int nDevId, int nBoard, unsigned short uMask16);

	TDC_API int GetG2Data(unsigned long long* data);

	TDC_API int G2Initialize(int nDevId, int nBoard, int ng2Mode, int nStartChl, int nStopChl, int nRes);

	TDC_API int G2ValueOfLocalFile(const char* strFileName);

	TDC_API int StopG2OfLocalFile();

	TDC_API bool IsG2CompletedOfFile(unsigned int* uProgress);

	TDC_API int GetG2Status(unsigned int* uXMax, unsigned int* uXLastNoZeroValue, unsigned long long* uYMax, unsigned long long* uSyncCount, unsigned long long* uChlCount, unsigned long long* uSyncTimes, unsigned long long* uChlTimes);

	TDC_API unsigned long long GetG2CollectionTime();

	TDC_API int MultiBodyInitialize(int nDevId, int nBoard, unsigned long long uTotalTimes);

	TDC_API int MultiBodyModeSelection(int nDevId, int nMethod);

	TDC_API int MultiBodyAddGroup(SingleGroup group[], int GroupSize);

	TDC_API int MultiBodyAddCluster(SingleCluster cluster[], int ClusterSize);

	TDC_API int MultiBodyStartOffLine(const char* strFileName);

	TDC_API int MultiBodyGetGroupCount(const char* strGroupName, unsigned long long* uGroupCount);

	TDC_API int MultiBodyGetClusterCount(const char* strClusterName, const char* strGroupName, unsigned long long* uClusterCount, unsigned long long* uGroupCount);

	TDC_API int MultiBodyGetChlCount(unsigned long long chlCnt[]);

	TDC_API int MultiBodyStopOffLine();

	TDC_API bool IsMultiCoCompletedOffLine(unsigned int* uProgress);

	TDC_API int StartTask(int nRunMode);

	TDC_API int StopTask(int nRunMode);

	TDC_API int PauseTask();

	TDC_API int ResumeTask();

	TDC_API int IsTaskCompleted();

	//用来，当磁盘不足时，任务终止原因的获取
	TDC_API bool IsOutOfDiskSpace();

	TDC_API int GetRunMode(unsigned int* uRunMode);

	TDC_API int SetMemoryDataMode(bool bEnable);

	TDC_API bool MemoryDataModeEnabled();

	TDC_API FtmtRawData* GetMemoryData(int nDevId);

	TDC_API int ReleaseMemoryData(FtmtRawData* ptrData);

	TDC_API int GetCollectTimes(int nDevId, unsigned long long* uColloctionTimes);

	TDC_API int StartChannelMapping(int nDevId, int nBoard, unsigned char uChannelMapping8);

	TDC_API int SaveConfigParam(int nDevId, int nBoard, unsigned int uValue);

	TDC_API int ReadRegister(int nDevId, unsigned char* ReadBuff, unsigned char len, unsigned int* ptrValue);

	TDC_API int WriteRegister(int nDevId, unsigned char* WriteBuff, unsigned char len, unsigned int Value);

	//上面的代码是用来定义函数的，可以简单理解为告诉MATLAB你有什么函数
	//下面的代码也是必须要有的别管为什么问就是去百度
#ifdef __cplusplus
}
#endif
#endif


